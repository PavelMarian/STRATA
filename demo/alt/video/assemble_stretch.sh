#!/usr/bin/env bash
# Cut from an existing recording: each scene's video is time-stretched to its voice-over length.
#   bash assemble_stretch.sh <rec dir> <voice dir> <out.mp4>
set -euo pipefail
REC="${1:?rec dir}"; VOICE="${2:?voice dir}"; OUT="${3:?out.mp4}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
: > "$TMP/clips.txt"
for d in $(ls -d "$REC"/frames/scene_* | awk -F"scene_" '{print $NF" "$0}' | sort -n | cut -d" " -f2-); do
  id="${d##*_}"; wav="$VOICE/scene_${id}.wav"; [ -f "$wav" ] || { echo "missing $wav" >&2; exit 1; }
  ffmpeg -y -v error -f concat -safe 0 -i "$d/frames.txt" -vf "scale=1920:1080:flags=lanczos,format=yuv420p" -r 30 -c:v libx264 -preset veryfast -crf 18 "$TMP/v_${id}.mp4"
  vd=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP/v_${id}.mp4"); ad=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")
  r=$(python3 -c "print(($ad+0.3)/$vd)")
  ffmpeg -y -v error -i "$TMP/v_${id}.mp4" -i "$wav" -filter_complex "[0:v]setpts=${r}*PTS[v];[1:a]loudnorm=I=-20:TP=-3:LRA=11,apad=pad_dur=0.3[a]" -map "[v]" -map "[a]" -r 30 -c:v libx264 -preset veryfast -crf 18 -c:a aac -b:a 160k -shortest "$TMP/clip_${id}.mp4"
  echo "file '$TMP/clip_${id}.mp4'" >> "$TMP/clips.txt"
  printf 'scene %s: video %.1f s, audio %.1f s, ratio %.2f\n' "$id" "$vd" "$ad" "$r"
done
ffmpeg -y -v error -f concat -safe 0 -i "$TMP/clips.txt" -c copy "$OUT"
echo "$OUT: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT") s"
