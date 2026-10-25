"""Synthetic SQLite benchmarks. Never imports app.py or reads DATABASE_URL.

python tests/benchmark_stats.py --output results.json
Each action runs in a fresh child process. Timing excludes tracemalloc overhead;
Python allocation peak is measured separately, RSS peak includes child startup.
"""
import argparse
import ctypes
import gc
import inspect
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'synthetic-benchmark-only')
warnings.filterwarnings('ignore', category=DeprecationWarning)

from flask import Flask, url_for
from flask_login import LoginManager
from sqlalchemy import event
from extensions import db, csrf
from models import Group, Member, Costume, PhotoType, CostumeTypeNormalization, Photo, User, UserPhoto, WantShare
from routes.photo import photo_bp
from routes.stats import stats_bp
from routes.share import share_bp
from services.stats_service import build_member_comp_data


def make_app(database):
    # Database location is supplied only by this synthetic harness.
    assert database.name == 'synthetic.sqlite'
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config.update(SECRET_KEY='synthetic-benchmark-only', TESTING=True,
                      SQLALCHEMY_DATABASE_URI='sqlite:///' + database.as_posix(),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, WTF_CSRF_ENABLED=False)
    db.init_app(app)
    csrf.init_app(app)
    manager = LoginManager(app)
    manager.user_loader(lambda uid: db.session.get(User, int(uid)))
    for bp in (photo_bp, stats_bp, share_bp):
        app.register_blueprint(bp)
    app.jinja_env.globals['url_for'] = lambda endpoint, **kw: (
        url_for(endpoint, **kw) if endpoint in app.view_functions else '/fixture/' + endpoint)
    return app


def seed(app, size):
    with app.app_context():
        db.create_all()
        db.session.add(Group(id=1, key='hinatazaka', name='Synthetic group'))
        db.session.add(User(id=100, firebase_uid='synthetic-100', username='Synthetic',
                            email='synthetic@example.invalid', primary_group='hinatazaka',
                            selected_groups='hinatazaka', plan_type='free'))
        db.session.flush()
        db.session.execute(Member.__table__.insert(), [dict(id=m, name=f'Member {m:03}', group_id=1,
                            generation=(m-1)//10+1, display_order=m) for m in range(1, 51)])
        costumes = math.ceil(size / 300)
        db.session.execute(Costume.__table__.insert(), [dict(id=c, name=f'Costume {c:04}', group_id=1)
                                                      for c in range(1, costumes+1)])
        db.session.execute(PhotoType.__table__.insert(), [dict(id=i, name=t) for i, t in enumerate(
            ('01', '02', '03', 'ヨリ（カンフー）', '座り', '特殊'), 1)])
        db.session.execute(CostumeTypeNormalization.__table__.insert(), [
            dict(costume_id=c, photo_type_id=t, normalized_type=label)
            for c in range(1, costumes+1) for t, label in enumerate(('ヨリ', 'チュウ', 'ヒキ'), 1)])
        db.session.add(WantShare(user_id=100, group_key='hinatazaka', public_uuid='synthetic', is_public=True))
        for start in range(0, size, 1000):
            indices = range(start, min(start+1000, size))
            db.session.execute(Photo.__table__.insert(), [dict(id=i+1, member_id=i%50+1,
                                costume_id=i//300+1, type_id=(i//50)%6+1) for i in indices])
            db.session.execute(UserPhoto.__table__.insert(), [dict(user_id=100, photo_id=i+1,
                                quantity=(i%4+1) if i%10 < 6 else 0, available_quantity=0)
                                for i in indices if i%10 < 7])
        db.session.commit()
        db.session.remove()
        db.engine.dispose()


def rss_peak_mib():
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize / 1024**2
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024**2 if sys.platform == 'darwin' else 1024)


def measure(database, action, samples):
    app = make_app(database)
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = '100'
        session['_fresh'] = True
    counts = []
    with app.app_context():
        def query_count(conn, cursor, statement, parameters, context, executemany):
            counts.append(statement.split(None, 1)[0])
        event.listen(db.engine, 'before_cursor_execute', query_count)
    def run():
        if action == 'member':
            with app.app_context():
                if 'member_id' in inspect.signature(build_member_comp_data).parameters:
                    result = build_member_comp_data(100, 'hinatazaka', member_id=1)
                else:
                    result = build_member_comp_data(100, 'hinatazaka', 'Member 001')
                return len(json.dumps(result))
        path = '/stats/hinatazaka' if action == 'stats' else '/shared/hinatazaka/synthetic'
        response = client.get(path)
        assert response.status_code == 200, response.status_code
        return len(response.data)
    run()  # Warm template/SQL compilation; no application data cache added.
    durations, query_counts, response_sizes = [], [], []
    for _ in range(samples):
        gc.collect()
        counts.clear()
        started = time.perf_counter()
        response_sizes.append(run())
        durations.append((time.perf_counter() - started) * 1000)
        query_counts.append(len(counts))
    gc.collect()
    tracemalloc.start()
    run()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(action=action, samples_ms=durations, median_ms=statistics.median(durations),
                max_ms=max(durations), query_counts=query_counts,
                python_peak_mib=peak/1024**2, process_peak_rss_mib=rss_peak_mib(),
                response_bytes=response_sizes[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sizes', nargs='+', type=int, default=[10000, 50000, 100000])
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--worker', choices=['stats', 'member', 'shared'])
    parser.add_argument('--database', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(measure(args.database, args.worker, args.samples)))
        return
    assert args.output and args.samples > 0
    results = dict(platform=platform.platform(), python=sys.version, sqlite=__import__('sqlite3').sqlite_version,
                   samples=args.samples, fixture=dict(members=50, types_per_costume=6,
                   positive_ownership_percent=60, zero_ownership_percent=10, quantities='1..4',
                   classified_numeric_db_mappings=True), results=[])
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix='spcolle-bench-') as directory:
            database = Path(directory) / 'synthetic.sqlite'
            seed(make_app(database), size)
            for action in ('stats', 'member', 'shared'):
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', action,
                    '--database', str(database), '--samples', str(args.samples)], capture_output=True, text=True)
                if completed.returncode:
                    raise RuntimeError(completed.stderr)
                result = dict(photos=size, **json.loads(completed.stdout))
                results['results'].append(result)
                print(json.dumps(result), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
