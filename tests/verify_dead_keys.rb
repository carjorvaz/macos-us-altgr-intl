#!/usr/bin/ruby
require "rexml/document"
require "rexml/xpath"

path = File.expand_path(ARGV.fetch(0, "../us-altgr-intl.keylayout"), __dir__)
raw = File.binread(path).gsub(/&#x([0-9A-Fa-f]+);/) do |reference|
  codepoint = Regexp.last_match(1).to_i(16)
  codepoint < 0x20 && ![9, 10, 13].include?(codepoint) ? "?" : reference
end
document = REXML::Document.new(raw)

class Simulator
  attr_reader :state

  def initialize(document)
    @document = document
    @state = "none"
  end

  def press(map_index, key_code)
    key = REXML::XPath.first(
      @document,
      "/keyboard/keyMapSet[@id='16c']/keyMap[@index='#{map_index}']/key[@code='#{key_code}']"
    )
    raise "missing map #{map_index}, key #{key_code}" unless key

    if key.attributes["output"]
      output = @state == "none" ? "" : terminator(@state)
      @state = "none"
      return output + key.attributes["output"]
    end

    action = key.attributes["action"]
    branch = REXML::XPath.first(
      @document,
      "/keyboard/actions/action[@id='#{action}']/when[@state='#{@state}']"
    )
    unless branch
      output = terminator(@state)
      @state = "none"
      return output + press(map_index, key_code)
    end

    @state = branch.attributes["next"] || "none"
    branch.attributes["output"].to_s
  end

  private

  def terminator(state)
    REXML::XPath.first(
      @document,
      "/keyboard/terminators/when[@state='#{state}']"
    ).attributes["output"].to_s
  end
end

def verify(document, label, steps, expected)
  simulator = Simulator.new(document)
  actual = steps.map { |map, key| simulator.press(map, key) }.join
  raise "#{label}: expected #{expected.inspect}, got #{actual.inspect}" unless actual == expected
  raise "#{label}: state did not reset" unless simulator.state == "none"
  puts "PASS: #{label}"
end

# Option+6 enters the AltGr circumflex state; Shift selects uppercase letters.
{0 => "Â", 14 => "Ê", 34 => "Î", 31 => "Ô", 32 => "Û", 16 => "Ŷ"}.each do |key, output|
  verify(document, "Option+6 then #{output}", [[3, 22], [1, key]], output)
end
verify(document, "Option+6 then Space", [[3, 22], [0, 49]], "^ ")

# Shift+Option+` enters the AltGr tilde state.
{0 => "Ã", 45 => "Ñ", 31 => "Õ"}.each do |key, output|
  verify(document, "Shift+Option+` then #{output}", [[4, 10], [1, key]], output)
end

# Shift+Option+/ enters hook-above; no leading whitespace is emitted.
verify(document, "Shift+Option+/ then a", [[4, 44], [0, 0]], "ả")
