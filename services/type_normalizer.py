# services/type_normalizer.py

"""
photo_type 正規化ユーティリティ

目的:
- 衣装ごとに異なる photo_type 表現（例: 01,02,03）を
  統一的な分類（ヨリ/チュウ/ヒキなど）へ変換する
- 統計処理・コンプ判定の一貫性を保つ
"""

from typing import Dict


# -----------------------------
# 衣装別 type 変換マップ
# -----------------------------
TYPE_NORMALIZATION_MAP: Dict[str, Dict[str, str]] = {

    # --- ひらがなけやき系 ---
    "2016.winter-07.08.09(ひらがなけやき)": {
        "07": "ヨリ",
        "08": "チュウ",
        "09": "ヒキ",
    },

    "2017.spring-01.02.03(ひらがなけやき)": {
        "01": "ヨリ",
        "02": "チュウ",
        "03": "ヒキ",
    },

    # 必要に応じて追加
}


# -----------------------------
# 正規化関数
# -----------------------------
def normalize_type(member: str, costume: str, photo_type: str) -> str:
    """
    photo_type を正規化する

    Parameters
    ----------
    member : str
        メンバー名（現状は未使用だが将来拡張用）
    costume : str
        衣装名
    photo_type : str
        元のタイプ（例: 01, ヨリ など）

    Returns
    -------
    str
        正規化されたタイプ
    """

    # 衣装単位でマッピング取得
    mapping = TYPE_NORMALIZATION_MAP.get(costume)

    if mapping:
        return mapping.get(photo_type, photo_type)

    # マッピング未定義ならそのまま返す
    return photo_type