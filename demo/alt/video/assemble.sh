#!/usr/bin/env bash
# Cut the demo video: per-scene frames from record.mjs + per-scene wavs from the voice-over skill.
#   bash assemble.sh <rec dir> <voice dir> <out.mp4>
# Each scene becomes one clip whose length is the voice-over length (the recorder already held the
# last frame that long); the voice is normalised to -20 LUFS with a -3 dBTP limiter, as in GateProbe.
set -euo pipefail
REC="${1:?rec dir (frames/scene_<id>/frames.txt)}"; VOICE="${2:?voice dir (scene_<id>.wav)}"; OUT="${3:?out.mp4}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
: > "$TMP/clips.txt"
for d in $(ls -d "$REC"/frames/scene_* | awk -F"scene_" '{print $NF" "$0}' | sort -n | cut -d" " -f2-); do
  id="${d##*_}"; wav="$VOICE/scene_${id}.wav"
  [ -f "$wav" ] || { echo "missing $wav" >&2; exit 1; }
  ffmpeg -y -v error -f concat -safe 0 -i "$d/frames.txt" -i "$wav" \
    -filter_complex "[1:a]loudnorm=I=-20:TP=-3:LRA=11[a]" -map 0:v -map "[a]" \
    -vf "scale=1920:1080:flags=lanczos,format=yuv420p" -r 30 -c:v libx264 -preset medium -crf 18 \
    -c:a aac -b:a 160k -shortest "$TMP/clip_${id}.mp4"
  echo "file '$TMP/clip_${id}.mp4'" >> "$TMP/clips.txt"
  echo "scene $id: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP/clip_${id}.mp4") s"
done
ffmpeg -y -v error -f concat -safe 0 -i "$TMP/clips.txt" -c copy "$OUT"
echo "$OUT: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT") s"
