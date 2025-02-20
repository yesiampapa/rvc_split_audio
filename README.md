# rvc-split_audio

`pip install pydub`

`chmod +x split.py`

```./split.py --input_dir path/to --output_dir path/to --min_silence_len 300 --silence_thresh -50 --min_sec 1 --max_sec 5 --fade_ms 10 --gap_ms 100```

---

`--input_dir` 入力フォルダ（複数ファイルがあっても可）

`--output_dir` 出力フォルダ

`--min_silence_len` 最小の無音長

`--silence_thresh` 無音のスレッショルド

`--min_sec` 分割ファイルの最短時間

`--max_sec` 分割ファイルの最長時間

`--fade_ms` 短いピース同士の結合時に発声するクリックを防ぐために適用するフェード時間

`--gap_ms` 短いピース同士の結合時のギャップ時間
