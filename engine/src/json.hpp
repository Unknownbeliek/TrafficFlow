// Minimal JSON reader/writer for Trackflow. No external dependencies (ES-251
// requires the numerical work to be plain C/C++; the project should build with
// nothing but a C++17 compiler and make).
#pragma once
#include <cctype>
#include <cmath>
#include <cstdio>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace tf {
namespace json {

struct Value;
using Object = std::map<std::string, Value>;
using Array = std::vector<Value>;

struct Value {
  enum Type { Null, Bool, Number, String, Arr, Obj } type = Null;
  bool b = false;
  double num = 0.0;
  std::string str;
  std::shared_ptr<Array> arr;
  std::shared_ptr<Object> obj;

  bool isNull() const { return type == Null; }
  bool isObj() const { return type == Obj; }
  bool isArr() const { return type == Arr; }
  bool isNum() const { return type == Number; }
  bool isStr() const { return type == String; }

  double asNum(double dflt = 0.0) const { return type == Number ? num : dflt; }
  int asInt(int dflt = 0) const { return type == Number ? (int)std::lround(num) : dflt; }
  bool asBool(bool dflt = false) const { return type == Bool ? b : dflt; }
  std::string asStr(const std::string &dflt = "") const { return type == String ? str : dflt; }

  const Array &items() const {
    static const Array empty;
    return arr ? *arr : empty;
  }
  bool has(const std::string &k) const { return obj && obj->count(k) > 0; }
  const Value &operator[](const std::string &k) const {
    static const Value nullValue;
    if (!obj) return nullValue;
    auto it = obj->find(k);
    return it == obj->end() ? nullValue : it->second;
  }
};

namespace detail {
struct Parser {
  const char *p;
  const char *end;

  void skip() {
    while (p < end) {
      char c = *p;
      if (c == ' ' || c == '\t' || c == '\n' || c == '\r') { ++p; continue; }
      if (c == '/' && p + 1 < end && p[1] == '/') {  // tolerate // comments
        while (p < end && *p != '\n') ++p;
        continue;
      }
      break;
    }
  }
  [[noreturn]] void fail(const char *msg) {
    throw std::runtime_error(std::string("json: ") + msg);
  }
  std::string parseString() {
    if (p >= end || *p != '"') fail("expected string");
    ++p;
    std::string out;
    while (p < end && *p != '"') {
      if (*p == '\\' && p + 1 < end) {
        ++p;
        switch (*p) {
          case 'n': out += '\n'; break;
          case 't': out += '\t'; break;
          case 'r': out += '\r'; break;
          case 'b': out += '\b'; break;
          case 'f': out += '\f'; break;
          case 'u': {
            // Escape sequences are rare in our data; keep the raw codepoint.
            unsigned code = 0;
            for (int i = 0; i < 4 && p + 1 < end; ++i) {
              ++p;
              char c = *p;
              code = code * 16 + (unsigned)(std::isdigit((unsigned char)c)
                                                ? c - '0'
                                                : (std::tolower(c) - 'a' + 10));
            }
            if (code < 0x80) out += (char)code;
            else out += '?';
            break;
          }
          default: out += *p; break;
        }
        ++p;
      } else {
        out += *p++;
      }
    }
    if (p >= end) fail("unterminated string");
    ++p;
    return out;
  }
  Value parseValue() {
    skip();
    if (p >= end) fail("unexpected end");
    Value v;
    char c = *p;
    if (c == '{') {
      ++p;
      v.type = Value::Obj;
      v.obj = std::make_shared<Object>();
      skip();
      if (p < end && *p == '}') { ++p; return v; }
      while (true) {
        skip();
        std::string key = parseString();
        skip();
        if (p >= end || *p != ':') fail("expected ':'");
        ++p;
        (*v.obj)[key] = parseValue();
        skip();
        if (p < end && *p == ',') { ++p; continue; }
        if (p < end && *p == '}') { ++p; break; }
        fail("expected ',' or '}'");
      }
      return v;
    }
    if (c == '[') {
      ++p;
      v.type = Value::Arr;
      v.arr = std::make_shared<Array>();
      skip();
      if (p < end && *p == ']') { ++p; return v; }
      while (true) {
        v.arr->push_back(parseValue());
        skip();
        if (p < end && *p == ',') { ++p; continue; }
        if (p < end && *p == ']') { ++p; break; }
        fail("expected ',' or ']'");
      }
      return v;
    }
    if (c == '"') {
      v.type = Value::String;
      v.str = parseString();
      return v;
    }
    if (c == 't' && end - p >= 4) { p += 4; v.type = Value::Bool; v.b = true; return v; }
    if (c == 'f' && end - p >= 5) { p += 5; v.type = Value::Bool; v.b = false; return v; }
    if (c == 'n' && end - p >= 4) { p += 4; return v; }
    // number
    const char *start = p;
    if (p < end && (*p == '-' || *p == '+')) ++p;
    while (p < end && (std::isdigit((unsigned char)*p) || *p == '.' || *p == 'e' || *p == 'E' ||
                       *p == '-' || *p == '+'))
      ++p;
    if (p == start) fail("unexpected character");
    v.type = Value::Number;
    v.num = std::strtod(std::string(start, p).c_str(), nullptr);
    return v;
  }
};
}  // namespace detail

inline Value parse(const std::string &text) {
  detail::Parser ps{text.c_str(), text.c_str() + text.size()};
  return ps.parseValue();
}

// ---- writer helpers -------------------------------------------------------
inline std::string escape(const std::string &s) {
  std::string out;
  out.reserve(s.size() + 2);
  for (char c : s) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\t': out += "\\t"; break;
      case '\r': out += "\\r"; break;
      default: out += c;
    }
  }
  return out;
}

// Compact fixed-precision number formatting: keeps snapshots small.
inline std::string num(double v, int prec = 2) {
  if (!std::isfinite(v)) return "0";
  char buf[40];
  std::snprintf(buf, sizeof buf, "%.*f", prec, v);
  std::string s(buf);
  if (s.find('.') != std::string::npos) {
    while (!s.empty() && s.back() == '0') s.pop_back();
    if (!s.empty() && s.back() == '.') s.pop_back();
  }
  if (s == "-0") s = "0";
  return s;
}

}  // namespace json
}  // namespace tf
