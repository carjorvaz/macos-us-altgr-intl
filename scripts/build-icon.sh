#!/bin/bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
source_svg="$repo_root/artwork/us-altgr-intl.svg"
output_icns="${1:-$repo_root/us-altgr-intl.bundle/Contents/Resources/us-altgr-intl.icns}"

if [[ ! -f "$source_svg" ]]; then
    printf 'Missing icon source: %s\n' "$source_svg" >&2
    exit 1
fi

tmp_dir="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/us-altgr-intl-icon.XXXXXX")"
iconset="$tmp_dir/us-altgr-intl.iconset"
trap '/bin/rm -rf -- "$tmp_dir"' EXIT

/bin/mkdir -p -- "$iconset"
output_dir="${output_icns%/*}"
if [[ "$output_dir" == "$output_icns" ]]; then
    output_dir='.'
fi
/bin/mkdir -p -- "$output_dir"

render_icon() {
    local dimension="$1"
    local filename="$2"
    /usr/bin/sips -s format png --resampleHeightWidth "$dimension" "$dimension" \
        "$source_svg" --out "$iconset/$filename" >/dev/null
}

render_icon 16 icon_16x16.png
render_icon 32 icon_16x16@2x.png
render_icon 32 icon_32x32.png
render_icon 64 icon_32x32@2x.png
render_icon 128 icon_128x128.png
render_icon 256 icon_128x128@2x.png
render_icon 256 icon_256x256.png
render_icon 512 icon_256x256@2x.png
render_icon 512 icon_512x512.png
render_icon 1024 icon_512x512@2x.png

/usr/bin/iconutil --convert icns --output "$output_icns" "$iconset"
