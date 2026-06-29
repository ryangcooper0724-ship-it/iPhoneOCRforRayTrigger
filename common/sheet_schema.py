"""Googleスプレッドシート「タイム表」の列構成・シート名などの共通定義。

sheets/uploader.py（Sheetsへの書き込み）とstorage/csv_mirror.py（ローカルCSVミラー）の
両方がこの列構成を参照する。storageがsheets層に依存しないよう、共通層であるここに置く。
sheets/template_setup.py（テンプレートの新規作成）の列構成とも対応している。
"""

BIB_COL = 2  # B列: ゼッケン（全フォーマット共通）

# フォーマットごとの (タイム列, P列, D列) の並び（1始まり）。template_setup.pyの列構成と対応している。
# 「通常の本数」として扱う列のみ。format2の練習走行は別途FORMAT_PRACTICE_SLOTで扱う。
FORMAT_RUN_SLOTS: dict[str, list[tuple[int, int, int]]] = {
    "format1": [(7, 8, 9), (10, 11, 12)],
    "format2": [(10, 11, 12), (13, 14, 15)],
    "format3": [(5 + 3 * i, 6 + 3 * i, 7 + 3 * i) for i in range(15)],
}
FORMAT_PRACTICE_SLOT: dict[str, tuple[int, int, int]] = {
    "format2": (7, 8, 9),
}
FORMAT_SHEET_NAME: dict[str, str] = {
    "format1": "タイム表",
    "format2": "タイム表",
    "format3": "午前",  # format3は午前/午後の2シートあり。write_result()のsheet_nameで上書きする
}
