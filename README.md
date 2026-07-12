# macos-us-altgr-intl

## Motivation

[US International (with AltGr dead-keys) on macOS](https://carjorvaz.com/posts/us-international-with-altgr-dead-keys-on-macos/)

Releases ship `us-altgr-intl.bundle`, including an original monochrome `AG` icon for the macOS input menu.

The layout is independently generated from pinned public XKB, X11 Compose,
keysym, Unicode, and Apple keyboard-format sources. It does not incorporate the
historical Twam/xv0x7c0 keyboard-layout XML. Exact source versions, hashes,
licenses, and derivation records live under [`layout/`](layout/).

## Installation

Download the source archive (`.zip` or `.tar.gz`) for the [latest GitHub release](https://github.com/carjorvaz/macos-us-altgr-intl/releases/latest), extract it, and run the commands below from the extracted directory.

Use exactly one installation scope. The recommended per-user install is:

```sh
set -eu
source_bundle="$PWD/us-altgr-intl.bundle"
install_dir="$HOME/Library/Keyboard Layouts"
installed_bundle="$install_dir/us-altgr-intl.bundle"

# Verify the source bundle before changing an existing installation.
test -f "$source_bundle/Contents/Info.plist"
test -f "$source_bundle/Contents/Resources/us-altgr-intl.keylayout"
test -f "$source_bundle/Contents/Resources/us-altgr-intl.icns"

mkdir -p "$install_dir"
stage="$(mktemp -d "$install_dir/.us-altgr-intl.bundle.XXXXXX")"
trap 'rm -rf "$stage"' EXIT HUP INT TERM
cp -R "$source_bundle/." "$stage/"
test -f "$stage/Contents/Info.plist"
test -f "$stage/Contents/Resources/us-altgr-intl.keylayout"
test -f "$stage/Contents/Resources/us-altgr-intl.icns"

rm -f "$install_dir/us-altgr-intl.keylayout"
rm -rf "$installed_bundle"
mv "$stage" "$installed_bundle"
trap - EXIT HUP INT TERM
```

If migrating from a legacy system-wide installation, run the per-user install successfully first, then remove both possible system-wide copies:

```sh
sudo rm -f "/Library/Keyboard Layouts/us-altgr-intl.keylayout"
sudo rm -rf "/Library/Keyboard Layouts/us-altgr-intl.bundle"
```

Alternatively, administrators can install for all users. This stages and verifies the complete system bundle before removing any user or system copy:

```sh
set -eu
source_bundle="$PWD/us-altgr-intl.bundle"
install_dir="/Library/Keyboard Layouts"
installed_bundle="$install_dir/us-altgr-intl.bundle"

# Verify the source bundle before changing an existing installation.
test -f "$source_bundle/Contents/Info.plist"
test -f "$source_bundle/Contents/Resources/us-altgr-intl.keylayout"
test -f "$source_bundle/Contents/Resources/us-altgr-intl.icns"

sudo mkdir -p "$install_dir"
stage="$(sudo mktemp -d "$install_dir/.us-altgr-intl.bundle.XXXXXX")"
trap 'sudo rm -rf "$stage"' EXIT HUP INT TERM
sudo cp -R "$source_bundle/." "$stage/"
sudo test -f "$stage/Contents/Info.plist"
sudo test -f "$stage/Contents/Resources/us-altgr-intl.keylayout"
sudo test -f "$stage/Contents/Resources/us-altgr-intl.icns"

rm -f "$HOME/Library/Keyboard Layouts/us-altgr-intl.keylayout"
rm -rf "$HOME/Library/Keyboard Layouts/us-altgr-intl.bundle"
sudo rm -f "$install_dir/us-altgr-intl.keylayout"
sudo rm -rf "$installed_bundle"
sudo mv "$stage" "$installed_bundle"
trap - EXIT HUP INT TERM
```

Never keep loose and bundled copies, or user and system copies, at the same time: they share a layout ID and can appear as duplicate input sources.

Log out and back in, or restart. Then open **System Settings → Keyboard → Text Input → Edit → + → Others → us-altgr-intl**.

The keyboard layout was tested on macOS Sonoma 14.3.1.

## Development

Regenerate and verify the sealed keyboard layout:

```sh
python3 layout/generate.py --check
python3 layout/verify.py
```

Rebuild the icon from its vector source:

```sh
scripts/build-icon.sh
```

Run the focused bundle, layout, and icon checks:

```sh
/usr/bin/ruby tests/verify_bundle.rb
```

## License

Repository-authored code and artwork are licensed under the
[GNU General Public License v3.0](LICENSE). Vendored data and notices retain
their respective upstream terms; see [`layout/NOTICES.txt`](layout/NOTICES.txt)
and [`layout/source-lock.json`](layout/source-lock.json).

## Sources and acknowledgments

- [xkeyboard-config](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config)
- [libX11 Compose data](https://gitlab.freedesktop.org/xorg/lib/libx11)
- [xorgproto keysym definitions](https://gitlab.freedesktop.org/xorg/proto/xorgproto)
- [Unicode Character Database](https://www.unicode.org/ucd/)
- [Apple TN2056](https://developer.apple.com/library/archive/technotes/tn2056/_index.html)
- [Ukelele](https://software.sil.org/ukelele/)
- [US International on OS X](https://www.twam.info/hardware/us-international-on-os-x) and
  [osx-us-altgr-intl](https://github.com/xv0x7c0/osx-us-altgr-intl), retained as
  historical project acknowledgments only
