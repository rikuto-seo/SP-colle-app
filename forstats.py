from models import Photo,UserPhoto
def get_all_photos(group_key):
    """
    指定グループの全写真を取得
    """
    return Photo.query.filter_by(group_key=group_key).all()

def get_user_photo_ids(user_id, group_key):
    """
    指定ユーザーが所持している写真IDのセット
    """
    return {up.photo_id for up in UserPhoto.query.filter_by(user_id=user_id, group_key=group_key).all()}

def compute_collection_stats(all_photos, owned_photo_ids):
    """
    all_photos: Photoオブジェクトのリスト
    owned_photo_ids: ユーザーが所持しているPhoto.idのセット

    メンバーごとの進捗などをまとめて返す
    """
    from collections import defaultdict

    stats = defaultdict(lambda: {'owned': 0, 'total': 0})

    for photo in all_photos:
        key = (photo.member, photo.costume)
        stats[key]['total'] += 1
        if photo.id in owned_photo_ids:
            stats[key]['owned'] += 1

    # 結果を整形して返す
    return stats
