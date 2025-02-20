#!/usr/bin/env python3

import os
import multiprocessing
from functools import partial
from pydub import AudioSegment, silence

########################################
# 1) 初期無音分割
########################################
def split_into_phrases(audio: AudioSegment,
                       min_silence_len=300,
                       silence_thresh=-40):
    """
    無音区間(min_silence_len ms & < silence_thresh dB)を境に分割。
    """
    return silence.split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        keep_silence=0
    )

########################################
# 2) 5秒を超えるフレーズを "音量の低い部分" で分割
########################################
def find_lowest_volume_split(ch: AudioSegment, search_range_ms=1000):
    """
    チャンク中央付近 ± (search_range_ms/2) を探索し、
    RMS(平均振幅)が最小の位置を探す簡易実装。
    """
    length = len(ch)
    if length <= search_range_ms:
        return length // 2  # 中央で切る

    mid = length // 2
    start_search = max(0, mid - search_range_ms // 2)
    end_search = min(length, mid + search_range_ms // 2)

    min_rms = float('inf')
    best_pos = mid
    step = 50  # 50ms刻み
    i = start_search
    while i < end_search:
        seg = ch[i : i+step]
        if seg.rms < min_rms:
            min_rms = seg.rms
            best_pos = i + step // 2
        i += step

    return best_pos

def split_by_low_volume(ch: AudioSegment, max_sec=5, fade_ms=10, search_ms=1000):
    """
    チャンクが max_sec(秒)超なら、
    "音量の低い箇所"でフェード分割(再帰)。
    """
    max_len = max_sec * 1000
    if len(ch) <= max_len:
        return [ch]

    result = []
    remaining = ch
    while len(remaining) > max_len:
        split_pos = find_lowest_volume_split(remaining, search_ms)
        left = remaining[:split_pos].fade_out(fade_ms)
        right = remaining[split_pos:].fade_in(fade_ms)

        # leftがまだ長すぎれば再帰
        if len(left) > max_len:
            result.extend(split_by_low_volume(left, max_sec, fade_ms, search_ms))
        else:
            result.append(left)

        remaining = right
    # 最後の残り
    result.append(remaining)
    return result

########################################
# 3) 短いチャンク(<1s) を結合 or パディング
########################################
def merge_chunks(chunks,
                 min_sec=1,
                 max_sec=5,
                 ideal_pad_sec=4,
                 fade_ms=10,
                 gap_ms=100):
    """
    - チャンク順に走査
    - 現在バッファが <1s なら次チャンクと合体(フェード+無音)して 5s以内ならOK
    - 合体できない or 合体相手がない場合はパディング(4秒くらい)
    - バッファが >=1s の場合も、次チャンクと合体して5s以内なら続ける
    """
    result = []
    buffer = AudioSegment.empty()

    for ch in chunks:
        if len(buffer) == 0:
            buffer = ch
        else:
            if len(buffer) < min_sec * 1000:
                # バッファが1秒未満
                if len(buffer) + len(ch) + gap_ms <= max_sec * 1000:
                    buffer = fade_merge(buffer, ch, fade_ms, gap_ms)
                else:
                    # 合体すると 5秒超 → buffer確定
                    if len(buffer) < min_sec * 1000:
                        buffer = pad_to_length(buffer, ideal_pad_sec * 1000)
                    result.append(buffer)
                    buffer = ch
            else:
                # バッファ >=1s
                if len(buffer) + len(ch) + gap_ms <= max_sec * 1000:
                    buffer = fade_merge(buffer, ch, fade_ms, gap_ms)
                else:
                    result.append(buffer)
                    buffer = ch

    # 最後の残り
    if len(buffer) > 0:
        if len(buffer) < min_sec * 1000:
            buffer = pad_to_length(buffer, ideal_pad_sec * 1000)
        result.append(buffer)

    return result

def fade_merge(ch1: AudioSegment, ch2: AudioSegment, fade_ms=10, gap_ms=100):
    gap = AudioSegment.silent(duration=gap_ms)
    ch1_faded = ch1.fade_out(fade_ms)
    ch2_faded = ch2.fade_in(fade_ms)
    return ch1_faded + gap + ch2_faded

def pad_to_length(ch: AudioSegment, target_ms: int):
    needed = target_ms - len(ch)
    if needed > 0:
        return ch + AudioSegment.silent(duration=needed)
    return ch

########################################
# メイン処理: 1ファイル単位
########################################
def process_one_wav(path,
                    output_dir,
                    min_silence_len,
                    silence_thresh,
                    min_sec,
                    max_sec,
                    fade_ms,
                    gap_ms):
    base = os.path.splitext(os.path.basename(path))[0]
    audio = AudioSegment.from_wav(path)

    # 1) 無音区間で分割
    phrases = split_into_phrases(audio, min_silence_len, silence_thresh)

    # 2) 5秒超チャンク → 音量の低い部分で再帰的に分割
    splitted = []
    for ph in phrases:
        if len(ph) > max_sec * 1000:
            sublist = split_by_low_volume(ph, max_sec, fade_ms)
            splitted.extend(sublist)
        else:
            splitted.append(ph)

    # 3) 短いチャンク(<1s) を結合 or パディング
    final_chunks = merge_chunks(splitted,
                                min_sec=min_sec,
                                max_sec=max_sec,
                                ideal_pad_sec=4,
                                fade_ms=fade_ms,
                                gap_ms=gap_ms)

    # 4) 出力
    os.makedirs(output_dir, exist_ok=True)
    for i, ch in enumerate(final_chunks, start=1):
        out_name = f"{base}_part{i:03d}.wav"
        out_path = os.path.join(output_dir, out_name)
        ch.export(out_path, format="wav")
        print(f"Exported: {out_path} (length={len(ch)} ms)")

########################################
# 対話形式メイン
########################################
def main():
    # プログラム自身が置かれているディレクトリを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("===============================================")
    print(" 音声ファイル分割＆整形スクリプト (対話形式版)")
    print("===============================================")
    print(" 以下の質問に答えてください。Enterのみで既定値が適用されます。\n")

    # --input_dir
    default_input = script_dir
    input_dir = input(f"[入力ディレクトリ] (デフォルト: {default_input}): ").strip()
    if not input_dir:
        input_dir = default_input

    # --output_dir
    default_output = os.path.join(script_dir, "split_output")
    output_dir = input(f"[出力ディレクトリ] (デフォルト: {default_output}): ").strip()
    if not output_dir:
        output_dir = default_output

    # --min_silence_len (int)
    default_min_silence_len = 300
    tmp = input(f"[min_silence_len] (デフォルト: {default_min_silence_len} ms): ").strip()
    if not tmp:
        min_silence_len = default_min_silence_len
    else:
        min_silence_len = int(tmp)

    # --silence_thresh (int)
    default_silence_thresh = -60
    tmp = input(f"[silence_thresh] (デフォルト: {default_silence_thresh} dB): ").strip()
    if not tmp:
        silence_thresh = default_silence_thresh
    else:
        silence_thresh = int(tmp)

    # --min_sec
    default_min_sec = 1
    tmp = input(f"[min_sec] (デフォルト: {default_min_sec} 秒): ").strip()
    if not tmp:
        min_sec = default_min_sec
    else:
        min_sec = int(tmp)

    # --max_sec
    default_max_sec = 5
    tmp = input(f"[max_sec] (デフォルト: {default_max_sec} 秒): ").strip()
    if not tmp:
        max_sec = default_max_sec
    else:
        max_sec = int(tmp)

    # --fade_ms
    default_fade_ms = 10
    tmp = input(f"[fade_ms] (デフォルト: {default_fade_ms} ms): ").strip()
    if not tmp:
        fade_ms = default_fade_ms
    else:
        fade_ms = int(tmp)

    # --gap_ms
    default_gap_ms = 100
    tmp = input(f"[gap_ms] (デフォルト: {default_gap_ms} ms): ").strip()
    if not tmp:
        gap_ms = default_gap_ms
    else:
        gap_ms = int(tmp)

    # --workers
    cpu_count = multiprocessing.cpu_count()
    print(f"\nCPUコア数: {cpu_count}")
    tmp = input(f"[workers] (並列数。未指定なら自動(推奨)): ").strip()
    if not tmp:
        workers = None
    else:
        workers = int(tmp)

    print("\n============ 入力確認 ============")
    print(f"  input_dir        = {input_dir}")
    print(f"  output_dir       = {output_dir}")
    print(f"  min_silence_len  = {min_silence_len}")
    print(f"  silence_thresh   = {silence_thresh}")
    print(f"  min_sec          = {min_sec}")
    print(f"  max_sec          = {max_sec}")
    print(f"  fade_ms          = {fade_ms}")
    print(f"  gap_ms           = {gap_ms}")
    print(f"  workers          = {workers if workers else '(auto)'}")
    print("===================================")

    # 対象WAVファイルを検索
    if not os.path.isdir(input_dir):
        print(f"エラー: 入力ディレクトリが存在しません: {input_dir}")
        return

    wav_files = [os.path.join(input_dir, f)
                 for f in os.listdir(input_dir)
                 if f.lower().endswith(".wav")]
    if not wav_files:
        print(f"指定フォルダ内に .wav ファイルが見つかりませんでした: {input_dir}")
        return

    print(f"\n{len(wav_files)} 件のWAVファイルを処理します...")

    # functools.partial で定数引数をバインド
    func = partial(
        process_one_wav,
        output_dir=output_dir,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        min_sec=min_sec,
        max_sec=max_sec,
        fade_ms=fade_ms,
        gap_ms=gap_ms
    )

    # 出力ディレクトリ作成
    os.makedirs(output_dir, exist_ok=True)

    # マルチプロセスで実行
    with multiprocessing.Pool(processes=workers) as pool:
        pool.map(func, wav_files)

    print("\nすべての処理が完了しました。")

if __name__ == "__main__":
    main()
