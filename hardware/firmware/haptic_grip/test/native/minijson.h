// Tiny JSON reader for the test vectors (objects, arrays, strings, numbers, bools, null).
#pragma once

#include <cctype>
#include <cstdlib>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace minijson {

struct Value {
  enum Kind { Null, Bool, Number, String, Array, Object } kind = Null;
  bool b = false;
  double num = 0;
  std::string str;
  std::vector<Value> arr;
  std::map<std::string, Value> obj;
  const Value& operator[](const std::string& k) const {
    auto it = obj.find(k);
    if (it == obj.end()) throw std::runtime_error("missing key " + k);
    return it->second;
  }
  bool has(const std::string& k) const { return obj.count(k) != 0; }
};

class Parser {
 public:
  explicit Parser(const std::string& s) : s_(s) {}
  Value parse() { Value v = value(); ws(); return v; }

 private:
  const std::string& s_;
  size_t i_ = 0;
  void ws() { while (i_ < s_.size() && isspace((unsigned char)s_[i_])) ++i_; }
  char peek() { ws(); return i_ < s_.size() ? s_[i_] : '\0'; }
  void expect(char c) { if (peek() != c) throw std::runtime_error(std::string("expected ") + c); ++i_; }
  Value value() {
    char c = peek();
    Value v;
    if (c == '{') {
      v.kind = Value::Object; ++i_;
      if (peek() == '}') { ++i_; return v; }
      while (true) {
        std::string k = string_lit();
        expect(':');
        v.obj[k] = value();
        if (peek() == ',') { ++i_; continue; }
        expect('}');
        return v;
      }
    }
    if (c == '[') {
      v.kind = Value::Array; ++i_;
      if (peek() == ']') { ++i_; return v; }
      while (true) {
        v.arr.push_back(value());
        if (peek() == ',') { ++i_; continue; }
        expect(']');
        return v;
      }
    }
    if (c == '"') { v.kind = Value::String; v.str = string_lit(); return v; }
    if (s_.compare(i_, 4, "true") == 0) { i_ += 4; v.kind = Value::Bool; v.b = true; return v; }
    if (s_.compare(i_, 5, "false") == 0) { i_ += 5; v.kind = Value::Bool; return v; }
    if (s_.compare(i_, 4, "null") == 0) { i_ += 4; return v; }
    char* end = nullptr;
    v.kind = Value::Number;
    v.num = strtod(s_.c_str() + i_, &end);
    if (end == s_.c_str() + i_) throw std::runtime_error("bad number");
    i_ = (size_t)(end - s_.c_str());
    return v;
  }
  std::string string_lit() {
    expect('"');
    std::string out;
    while (i_ < s_.size() && s_[i_] != '"') {
      if (s_[i_] == '\\') { ++i_; out += s_[i_]; } else { out += s_[i_]; }
      ++i_;
    }
    ++i_;
    return out;
  }
};

inline std::vector<uint8_t> unhex(const std::string& h) {
  std::vector<uint8_t> out;
  for (size_t i = 0; i + 1 < h.size(); i += 2) out.push_back((uint8_t)std::stoul(h.substr(i, 2), nullptr, 16));
  return out;
}

}  // namespace minijson
