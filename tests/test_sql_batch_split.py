from scripts.setup_db import split_batches


def test_split_batches_on_go_lines():
    sql = "SELECT 1;\nGO\nSELECT 2;\ngo\n"
    assert split_batches(sql) == ["SELECT 1;", "SELECT 2;"]
