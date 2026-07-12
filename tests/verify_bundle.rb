#!/usr/bin/ruby
require "open3"
require "rexml/document"
require "rexml/xpath"
require "tmpdir"

ROOT = File.expand_path("..", __dir__)
BUNDLE = File.join(ROOT, "us-altgr-intl.bundle")
CONTENTS = File.join(BUNDLE, "Contents")
RESOURCES = File.join(CONTENTS, "Resources")
INFO_PLIST = File.join(CONTENTS, "Info.plist")
VERSION_PLIST = File.join(CONTENTS, "version.plist")
KEYLAYOUT = File.join(RESOURCES, "us-altgr-intl.keylayout")
ICON = File.join(RESOURCES, "us-altgr-intl.icns")
SVG = File.join(ROOT, "artwork", "us-altgr-intl.svg")
ICON_BUILDER = File.join(ROOT, "scripts", "build-icon.sh")
LAYOUT_ROOT = File.join(ROOT, "layout")
LAYOUT_SOURCE = File.join(LAYOUT_ROOT, "us-altgr-intl.keylayout")
LAYOUT_GENERATOR = File.join(LAYOUT_ROOT, "generate.py")
LAYOUT_VERIFIER = File.join(LAYOUT_ROOT, "verify.py")
LAYOUT_LOCK = File.join(LAYOUT_ROOT, "source-lock.json")
LAYOUT_NOTICES = File.join(LAYOUT_ROOT, "NOTICES.txt")


def check(condition, message)
  abort("FAIL: #{message}") unless condition
end


def pass(message)
  puts("PASS: #{message}")
end


def parse_xml(path)
  REXML::Document.new(File.binread(path))
rescue REXML::ParseException => error
  abort("FAIL: cannot parse #{path}: #{error.message}")
end


def plist_dict(element)
  children = element.elements.to_a
  check(children.length.even?, "plist dictionary has an unmatched key")

  children.each_slice(2).each_with_object({}) do |(key, value), result|
    check(key.name == "key", "plist dictionary entry does not begin with a key")
    result[key.text.to_s] = case value.name
                           when "string" then value.text.to_s
                           when "true" then true
                           when "false" then false
                           when "dict" then plist_dict(value)
                           else
                             abort("FAIL: unsupported plist value type #{value.name}")
                           end
  end
end


def parse_plist(path)
  document = parse_xml(path)
  dictionary = REXML::XPath.first(document, "/plist/dict")
  check(dictionary, "#{path} has no top-level dictionary")
  plist_dict(dictionary)
end


XML_REFERENCE = /&#(?:(x)([0-9A-Fa-f]+)|([0-9]+));/
XML_RESTRICTED = lambda do |codepoint|
  (0x01..0x08).cover?(codepoint) ||
    [0x0B, 0x0C].include?(codepoint) ||
    (0x0E..0x1F).cover?(codepoint) ||
    (0x7F..0x84).cover?(codepoint) ||
    (0x86..0x9F).cover?(codepoint)
end


def valid_xml_character?(codepoint)
  (0x01..0xD7FF).cover?(codepoint) ||
    (0xE000..0xFFFD).cover?(codepoint) ||
    (0x10000..0x10FFFF).cover?(codepoint)
end


def prepare_keylayout_xml(raw)
  if raw.match?(/__XML_REF_[0-9A-F]{6}__/)
    raise(ArgumentError, "keylayout contains reserved XML reference sentinel")
  end

  raw.gsub(XML_REFERENCE) do |reference|
    codepoint = if Regexp.last_match(1)
                  Regexp.last_match(2).to_i(16)
                else
                  Regexp.last_match(3).to_i(10)
                end
    raise(ArgumentError, "invalid XML character reference #{reference}") unless valid_xml_character?(codepoint)

    XML_RESTRICTED.call(codepoint) ? "__XML_REF_%06X__" % codepoint : reference
  end
end


def decode_xml_references(value)
  value.gsub(/__XML_REF_([0-9A-F]{6})__/) do
    [Regexp.last_match(1).to_i(16)].pack("U")
  end
end


def parse_keylayout(path)
  REXML::Document.new(prepare_keylayout_xml(File.binread(path)))
rescue ArgumentError, REXML::ParseException => error
  abort("FAIL: cannot parse keylayout: #{error.message}")
end


def run!(*command)
  stdout, stderr, status = Open3.capture3(*command)
  return stdout + stderr if status.success?

  abort("FAIL: #{command.join(' ')} exited #{status.exitstatus}:\n#{stdout}#{stderr}")
end

required_paths = [
  BUNDLE, INFO_PLIST, VERSION_PLIST, KEYLAYOUT, ICON, SVG, ICON_BUILDER,
  LAYOUT_SOURCE, LAYOUT_GENERATOR, LAYOUT_VERIFIER, LAYOUT_LOCK, LAYOUT_NOTICES
]
required_paths.each { |path| check(File.exist?(path), "missing #{path.sub(ROOT + '/', '')}") }
check(File.directory?(BUNDLE), "bundle path is not a directory")
check(File.executable?(ICON_BUILDER), "scripts/build-icon.sh is not executable")
check(!File.exist?(File.join(ROOT, "us-altgr-intl.keylayout")), "obsolete root keylayout still exists")

layout_stems = Dir.glob(File.join(RESOURCES, "*.keylayout")).map { |path| File.basename(path, ".keylayout") }
icon_stems = Dir.glob(File.join(RESOURCES, "*.icns")).map { |path| File.basename(path, ".icns") }
check(layout_stems == ["us-altgr-intl"], "unexpected keylayout resources: #{layout_stems.inspect}")
check(icon_stems == layout_stems, "ICNS and keylayout resource stems differ")
pass("bundle structure and paired resources")
check(File.binread(KEYLAYOUT) == File.binread(LAYOUT_SOURCE), "bundled keylayout differs from the sealed generated source")
run!("/usr/bin/python3", LAYOUT_GENERATOR, "--check")
run!("/usr/bin/python3", LAYOUT_VERIFIER)
pass("sealed clean-room layout generation and verification")

info = parse_plist(INFO_PLIST)
expected_info = {
  "CFBundleDevelopmentRegion" => "en",
  "CFBundleIdentifier" => "com.carjorvaz.keyboardlayout.us-altgr-intl",
  "CFBundleInfoDictionaryVersion" => "6.0",
  "CFBundleName" => "us-altgr-intl",
  "CFBundlePackageType" => "BNDL",
  "CFBundleShortVersionString" => "1.0",
  "CFBundleVersion" => "1",
  "KLInfo_us-altgr-intl" => {
    "TISIconIsTemplate" => true,
    "TISInputSourceID" => "com.carjorvaz.keyboardlayout.us-altgr-intl.layout",
    "TISIntendedLanguage" => "en"
  }
}
check(info == expected_info, "Info.plist values differ from the bundle contract")

version = parse_plist(VERSION_PLIST)
expected_version = {
  "BuildVersion" => "1",
  "CFBundleShortVersionString" => "1.0",
  "CFBundleVersion" => "1",
  "ProjectName" => "macos-us-altgr-intl",
  "SourceVersion" => "1"
}
check(version == expected_version, "version.plist values differ from the bundle contract")
pass("bundle metadata")

layout_document = parse_keylayout(KEYLAYOUT)
root = layout_document.root
check(root && root.name == "keyboard", "keylayout root is not <keyboard>")
check(root.attributes["name"] == "us-altgr-intl", "unexpected keyboard name")

reference_probe = REXML::Document.new(
  prepare_keylayout_xml('<probe hex="&#x1;" decimal="&#11;" ordinary="&#x10FFFF;"/>')
).root
check(decode_xml_references(reference_probe.attributes["hex"]) == "\u0001", "hexadecimal XML 1.1 control reference was not preserved")
check(decode_xml_references(reference_probe.attributes["decimal"]) == "\u000B", "decimal XML 1.1 control reference was not preserved")
check(reference_probe.attributes["ordinary"].codepoints == [0x10FFFF], "ordinary legal XML character reference was masked")
[1, 0xD7FF, 0xE000, 0xFFFD, 0x10000, 0x10FFFF].each do |codepoint|
  check(valid_xml_character?(codepoint), "U+%04X was rejected as an XML character" % codepoint)
end
[0, 0xD800, 0xDFFF, 0xFFFE, 0xFFFF, 0x110000].each do |codepoint|
  check(!valid_xml_character?(codepoint), "U+%04X was accepted as an XML character" % codepoint)
  ["&#x#{codepoint.to_s(16)};", "&##{codepoint};"].each do |reference|
    rejected = begin
      prepare_keylayout_xml("<probe value=\"#{reference}\"/>")
      false
    rescue ArgumentError
      true
    end
    check(rejected, "invalid XML character reference #{reference} was not rejected before parsing")
  end
end
pass("XML 1.1 hexadecimal and decimal character references")

PHYSICAL_MODIFIERS = [
  :left_shift, :right_shift,
  :left_option, :right_option,
  :left_control, :right_control,
  :command, :caps
].freeze

MODIFIER_FAMILIES = {
  "Shift" => [:left_shift, :right_shift, "shift", "rightShift", "anyShift"],
  "Option" => [:left_option, :right_option, "option", "rightOption", "anyOption"],
  "Control" => [:left_control, :right_control, "control", "rightControl", "anyControl"]
}.freeze


class LayoutSimulator
  attr_reader :map_set, :state

  def initialize(document, hardware_id)
    @document = document
    @state = "none"
    layouts = REXML::XPath.match(document, "/keyboard/layouts/layout")
    layout = layouts.find do |candidate|
      (candidate.attributes["first"].to_i..candidate.attributes["last"].to_i).cover?(hardware_id)
    end || layouts.first
    raise("keyboard has no hardware layouts") unless layout

    @map_set = layout.attributes["mapSet"]
    @modifier_map = REXML::XPath.first(
      document,
      "/keyboard/modifierMap[@id='#{layout.attributes['modifiers']}']"
    )
    raise("layout for hardware ID #{hardware_id} has no modifier map") unless @modifier_map
  end

  def map_index(modifiers)
    selected = @modifier_map.attributes["defaultIndex"].to_i
    @modifier_map.elements.each("keyMapSelect") do |selection|
      if selection.elements.to_a("modifier").any? { |modifier| modifier_matches?(modifier.attributes["keys"], modifiers) }
        selected = selection.attributes["mapIndex"].to_i
      end
    end
    selected
  end

  def press(modifiers, key_code)
    index = map_index(modifiers)
    key = resolve_key(@map_set, index, key_code)
    raise("missing hardware mapSet=#{@map_set} map=#{index} code=#{key_code}") unless key

    if @state != "none" && key.attributes["output"]
      output = terminator(@state) + decode(key.attributes["output"])
      @state = "none"
      return output
    end

    return decode(key.attributes["output"]) if key.attributes["output"]

    action = key.attributes["action"]
    raise("key has neither output nor action") unless action

    branch = REXML::XPath.first(
      @document,
      "/keyboard/actions/action[@id='#{action}']/when[@state='#{@state}']"
    )
    unless branch
      output = terminator(@state)
      @state = "none"
      return output + press(modifiers, key_code)
    end

    output = decode(branch.attributes["output"] || "")
    @state = branch.attributes["next"] || "none"
    output
  end

  private

  def modifier_matches?(keys, modifiers)
    tokens = keys.to_s.split
    matched_tokens = []

    MODIFIER_FAMILIES.each_value do |left, right, left_token, right_token, any_token|
      family_tokens = tokens.select { |token| [left_token, right_token, any_token].include?(token.delete_suffix("?")) }
      matched_tokens.concat(family_tokens)
      next if family_tokens.include?("#{any_token}?")

      if family_tokens.include?(any_token)
        return false unless modifiers[left] || modifiers[right]
        next
      end

      [[left, left_token], [right, right_token]].each do |physical, token|
        required = family_tokens.include?(token)
        optional = family_tokens.include?("#{token}?")
        return false if required && !modifiers[physical]
        return false if !required && !optional && modifiers[physical]
      end
    end

    [[:command, "command"], [:caps, "caps"]].each do |physical, token|
      matching = tokens.find { |candidate| candidate.delete_suffix("?") == token }
      matched_tokens << matching if matching
      return false if matching == token && !modifiers[physical]
      return false if matching.nil? && modifiers[physical]
    end

    unknown = tokens - matched_tokens
    raise("unknown modifier tokens: #{unknown.join(' ')}") unless unknown.empty?
    true
  end

  def resolve_key(map_set, index, key_code)
    key_map = REXML::XPath.first(
      @document,
      "/keyboard/keyMapSet[@id='#{map_set}']/keyMap[@index='#{index}']"
    )
    raise("missing keyMapSet=#{map_set} index=#{index}") unless key_map

    override = key_map.elements.to_a("key").find { |key| key.attributes["code"].to_i == key_code }
    return override if override

    base_set = key_map.attributes["baseMapSet"]
    return nil unless base_set

    resolve_key(base_set, key_map.attributes["baseIndex"].to_i, key_code)
  end

  def terminator(state)
    node = REXML::XPath.first(@document, "/keyboard/terminators/when[@state='#{state}']")
    decode(node ? node.attributes["output"].to_s : "")
  end

  def decode(value)
    decode_xml_references(value)
  end
end


def intended_map_index(modifiers)
  shifted = modifiers[:left_shift] || modifiers[:right_shift]
  option = modifiers[:left_option] || modifiers[:right_option]
  control = modifiers[:left_control] || modifiers[:right_control]

  return shifted ? 11 : 10 if modifiers[:command]
  return shifted ? 9 : 8 if control
  return modifiers[:caps] ? (shifted ? 7 : 6) : (shifted ? 3 : 2) if option
  return modifiers[:caps] ? (shifted ? 5 : 4) : (shifted ? 1 : 0)
end


expected_layouts = [[0, 17, "ANSI", "modifiers"]]
actual_layouts = REXML::XPath.match(layout_document, "/keyboard/layouts/layout").map do |layout|
  [
    layout.attributes["first"].to_i,
    layout.attributes["last"].to_i,
    layout.attributes["mapSet"],
    layout.attributes["modifiers"]
  ]
end
check(actual_layouts == expected_layouts, "hardware layout ranges differ: #{actual_layouts.inspect}")

((0..255).to_a + [999]).each do |hardware_id|
  actual_map_set = LayoutSimulator.new(layout_document, hardware_id).map_set
  check(actual_map_set == "ANSI", "hardware #{hardware_id} fallback resolves to #{actual_map_set}, expected ANSI")
end


modifier_simulator = LayoutSimulator.new(layout_document, 0)
256.times do |mask|
  modifiers = PHYSICAL_MODIFIERS.each_with_index.each_with_object({}) do |(modifier, bit), result|
    result[modifier] = (mask & (1 << bit)) != 0
  end
  expected = intended_map_index(modifiers)
  actual = modifier_simulator.map_index(modifiers)
  check(actual == expected, "modifier combination #{modifiers.inspect} selected map #{actual}, expected #{expected}")
end
pass("TN2056 ordered modifier selection for all 256 physical combinations")


def check_sequence(document, hardware_id, label, steps, expected)
  simulator = LayoutSimulator.new(document, hardware_id)
  output = steps.map { |modifiers, key_code| simulator.press(modifiers, key_code) }.join
  expected_points = expected.codepoints.map { |point| "U+%04X" % point }.join(" ")
  actual_points = output.codepoints.map { |point| "U+%04X" % point }.join(" ")
  check(output == expected, "hardware #{hardware_id} #{label}: expected #{expected_points}, got #{actual_points}")
  check(simulator.state == "none", "hardware #{hardware_id} #{label}: dead-key state did not reset")
end

none = {}
shift = { left_shift: true }
option = { left_option: true }
shift_option = { left_shift: true, left_option: true }
control = { left_control: true }

[0, 18].each do |hardware_id|
  check_sequence(layout_document, hardware_id, "Option+6 then a", [[option, 22], [none, 0]], "â")
  {
    0 => "Â",
    14 => "Ê",
    34 => "Î",
    31 => "Ô",
    32 => "Û",
    16 => "Ŷ"
  }.each do |key_code, expected|
    check_sequence(layout_document, hardware_id, "Option+6 then #{expected}", [[option, 22], [shift, key_code]], expected)
  end
  check_sequence(layout_document, hardware_id, "Option+Shift+/ then a", [[shift_option, 44], [none, 0]], "ả")
  { 0 => "Ã", 45 => "Ñ", 31 => "Õ" }.each do |key_code, expected|
    check_sequence(layout_document, hardware_id, "Option+Shift+` then #{expected}", [[shift_option, 50], [shift, key_code]], expected)
  end
  check_sequence(layout_document, hardware_id, "Shift+6 literal output", [[shift, 22]], "^")
  check_sequence(layout_document, hardware_id, "Control+A", [[control, 0]], "\u0001")
  check_sequence(layout_document, hardware_id, "Option+6 then Space", [[option, 22], [none, 49]], "^")
  check_sequence(layout_document, hardware_id, "Option+6 then direct f", [[option, 22], [none, 3]], "^f")
end

{
  "s_dead_hook" => "̉",
  "s_dead_tilde" => "~",
  "s_dead_circumflex" => "^",
  "s_dead_diaeresis" => "\""
}.each do |state, expected|
  terminator = REXML::XPath.first(layout_document, "/keyboard/terminators/when[@state='#{state}']")
  check(terminator && terminator.attributes["output"] == expected, "#{state} terminator differs")
end
pass("ANSI fallback, AltGr dead keys, literal caret, and Control-A behavior")

expected_icons = {
  "icon_16x16.png" => 16,
  "icon_16x16@2x.png" => 32,
  "icon_32x32.png" => 32,
  "icon_32x32@2x.png" => 64,
  "icon_128x128.png" => 128,
  "icon_128x128@2x.png" => 256,
  "icon_256x256.png" => 256,
  "icon_256x256@2x.png" => 512,
  "icon_512x512.png" => 512,
  "icon_512x512@2x.png" => 1024
}

def read_bmp(path)
  data = File.binread(path)
  check(data.bytesize >= 54, "#{path} has a truncated BMP header")
  check(data.byteslice(0, 2) == "BM", "#{path} is not a BMP")
  pixel_offset = data.byteslice(10, 4).unpack1("V")
  dib_size = data.byteslice(14, 4).unpack1("V")
  check(dib_size >= 40, "#{path} has unsupported BMP header size #{dib_size}")
  check(data.bytesize >= 14 + dib_size, "#{path} has a truncated BMP DIB header")
  width = data.byteslice(18, 4).unpack1("l<")
  stored_height = data.byteslice(22, 4).unpack1("l<")
  planes = data.byteslice(26, 2).unpack1("v")
  bits_per_pixel = data.byteslice(28, 2).unpack1("v")
  compression = data.byteslice(30, 4).unpack1("V")
  check(width.positive? && !stored_height.zero?, "#{path} has invalid BMP dimensions #{width}x#{stored_height}")
  check(planes == 1 && bits_per_pixel == 32, "#{path} is not a 32-bit BMP")
  check([0, 3].include?(compression), "#{path} uses unsupported BMP compression #{compression}")

  masks = if compression.zero?
            [0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000]
          else
            check(dib_size >= 56, "#{path} BI_BITFIELDS header has no alpha mask")
            check(data.bytesize >= 70, "#{path} has truncated BMP channel masks")
            data.byteslice(54, 16).unpack("V4")
          end
  check(masks.none?(&:zero?), "#{path} has an empty BMP channel mask")
  combined_mask = 0
  masks.each do |mask|
    check((combined_mask & mask).zero?, "#{path} has overlapping BMP channel masks")
    combined_mask |= mask
    shifted = mask >> ((mask & -mask).bit_length - 1)
    check((shifted & (shifted + 1)).zero?, "#{path} has a non-contiguous BMP channel mask")
  end
  expected_masks = [0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000]
  check(masks == expected_masks, "#{path} uses unsupported BMP channel masks #{masks.map { |mask| "0x%08X" % mask }.join(", ")}")

  decode_channel = lambda do |value, mask|
    shift = (mask & -mask).bit_length - 1
    maximum = mask >> shift
    (((value & mask) >> shift) * 255 + maximum / 2) / maximum
  end

  height = stored_height.abs
  row_bytes = width * 4
  check(data.bytesize >= pixel_offset + row_bytes * height, "#{path} has truncated pixel data")
  pixels = Array.new(width * height)
  height.times do |y|
    stored_y = stored_height.positive? ? height - 1 - y : y
    row_offset = pixel_offset + stored_y * row_bytes
    width.times do |x|
      value = data.byteslice(row_offset + x * 4, 4).unpack1("V")
      pixels[y * width + x] = masks.map { |mask| decode_channel.call(value, mask) }
    end
  end
  [width, height, pixels]
end


def convert_iconset(icon, iconset)
  run!("/usr/bin/iconutil", "--convert", "iconset", "--output", iconset, icon)
  iconset
end


def decoded_icon(path, bmp_path)
  run!("/usr/bin/sips", "--setProperty", "format", "bmp", path, "--out", bmp_path)
  read_bmp(bmp_path)
end


Dir.mktmpdir("us-altgr-intl-verify") do |directory|
  regenerated_icon = File.join(directory, "us-altgr-intl.icns")
  run!(ICON_BUILDER, regenerated_icon)

  committed_iconset = convert_iconset(ICON, File.join(directory, "committed.iconset"))
  regenerated_iconset = convert_iconset(regenerated_icon, File.join(directory, "regenerated.iconset"))
  expected_members = expected_icons.keys.sort
  {
    "committed" => committed_iconset,
    "regenerated" => regenerated_iconset
  }.each do |label, iconset|
    actual_members = Dir.children(iconset).sort
    check(actual_members == expected_members, "#{label} ICNS representations differ: #{actual_members.inspect}")
  end

  committed_decoded = {}
  expected_icons.each do |filename, expected_dimension|
    committed = decoded_icon(
      File.join(committed_iconset, filename),
      File.join(directory, "committed-#{filename}.bmp")
    )
    regenerated = decoded_icon(
      File.join(regenerated_iconset, filename),
      File.join(directory, "regenerated-#{filename}.bmp")
    )
    [committed, regenerated].each_with_index do |(width, height, _pixels), source_index|
      source = source_index.zero? ? "committed" : "regenerated"
      check(
        width == expected_dimension && height == expected_dimension,
        "#{source} #{filename} is #{width}x#{height}, expected #{expected_dimension}x#{expected_dimension}"
      )
    end
    check(committed == regenerated, "#{filename} decoded pixels differ from the SVG-generated representation")
    committed_decoded[filename] = committed
  end

  {
    "icon_16x16.png" => { clear: [[4, 8], [11, 5]], opaque: [2, 8] },
    "icon_128x128.png" => { clear: [[34, 64], [104, 68]], opaque: [72, 64] }
  }.each do |filename, samples|
    width, height, pixels = committed_decoded.fetch(filename)
    pixel_at = ->(x, y) { pixels.fetch(y * width + x) }
    samples[:clear].each do |x, y|
      check(pixel_at.call(x, y)[3].zero?, "#{filename} AG cutout sample #{x},#{y} is not transparent")
    end
    opaque_x, opaque_y = samples[:opaque]
    check(pixel_at.call(opaque_x, opaque_y)[3] == 255, "#{filename} tile sample is not opaque")
    visible = pixels.select { |pixel| pixel[3].positive? }
    check(visible.all? { |red, green, blue, _alpha| red.zero? && green.zero? && blue.zero? }, "#{filename} has visible non-black pixels")
    interior_alphas = (1...(height - 1)).flat_map do |y|
      (1...(width - 1)).map { |x| pixel_at.call(x, y)[3] }
    end
    check(interior_alphas.any?(&:zero?), "#{filename} interior has no transparent pixels")
    check(interior_alphas.include?(255), "#{filename} interior has no opaque pixels")
  end
end
pass("source-equivalent ICNS pixels and AG template transparency")
puts("PASS: all focused checks")
