// Minimal read-only JSON parser for Trackflow's network files.
//
// The engine has to load network.json without third-party dependencies, so this
// is a self-contained recursive-descent parser covering the subset the compiler
// emits: objects, arrays, strings, numbers, booleans and null.  It is
// deliberately read-only and allocation-light enough for a 250 kB file.
#pragma once

#include <cmath>
#include <cstdlib>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace tj {

struct Value {
    enum Type { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
    bool b = false;
    double n = 0.0;
    std::string s;
    std::vector<Value> a;
    std::map<std::string, Value> o;

    bool is_null() const { return t == NUL; }
    bool is_num() const { return t == NUM; }
    bool is_arr() const { return t == ARR; }
    bool is_obj() const { return t == OBJ; }

    bool has(const std::string &k) const { return t == OBJ && o.count(k) > 0; }

    const Value &operator[](const std::string &k) const {
        static const Value kNull;
        if (t != OBJ) return kNull;
        auto it = o.find(k);
        return it == o.end() ? kNull : it->second;
    }
    const Value &operator[](size_t i) const {
        static const Value kNull;
        return i < a.size() ? a[i] : kNull;
    }

    size_t size() const { return t == ARR ? a.size() : (t == OBJ ? o.size() : 0); }

    double num(const std::string &k, double d = 0.0) const {
        const Value &v = (*this)[k];
        return v.t == NUM ? v.n : d;
    }
    std::string str(const std::string &k, const std::string &d = std::string()) const {
        const Value &v = (*this)[k];
        return v.t == STR ? v.s : d;
    }
    bool boolean(const std::string &k, bool d = false) const {
        const Value &v = (*this)[k];
        return v.t == BOOL ? v.b : d;
    }
    const std::vector<Value> &arr(const std::string &k) const {
        static const std::vector<Value> kEmpty;
        const Value &v = (*this)[k];
        return v.t == ARR ? v.a : kEmpty;
    }
};

class Parser {
public:
    explicit Parser(const std::string &text) : p_(text.c_str()), begin_(text.c_str()) {}

    Value parse() {
        skip();
        Value v = value();
        skip();
        return v;
    }

private:
    const char *p_;
    const char *begin_;

    [[noreturn]] void fail(const std::string &msg) const {
        throw std::runtime_error("json: " + msg + " at offset " +
                                 std::to_string(p_ - begin_));
    }
    void skip() {
        for (;;) {
            while (*p_ == ' ' || *p_ == '\t' || *p_ == '\n' || *p_ == '\r') ++p_;
            if (p_[0] == '/' && p_[1] == '/') {
                while (*p_ && *p_ != '\n') ++p_;
                continue;
            }
            break;
        }
    }
    bool accept(char c) {
        skip();
        if (*p_ == c) { ++p_; return true; }
        return false;
    }
    void expect(char c) {
        skip();
        if (*p_ != c) fail(std::string("expected '") + c + "'");
        ++p_;
    }

    Value value() {
        skip();
        Value v;
        switch (*p_) {
            case '{': v = object(); break;
            case '[': v = array(); break;
            case '"': v.t = Value::STR; v.s = string(); break;
            case 't': literal("true"); v.t = Value::BOOL; v.b = true; break;
            case 'f': literal("false"); v.t = Value::BOOL; v.b = false; break;
            case 'n': literal("null"); v.t = Value::NUL; break;
            default: v.t = Value::NUM; v.n = number(); break;
        }
        return v;
    }

    void literal(const char *word) {
        size_t i = 0;
        while (word[i]) {
            if (p_[i] != word[i]) fail(std::string("bad literal ") + word);
            ++i;
        }
        p_ += i;
    }

    double number() {
        skip();
        char *end = nullptr;
        double d = std::strtod(p_, &end);
        if (end == p_) fail("bad number");
        p_ = end;
        return d;
    }

    std::string string() {
        expect('"');
        std::string out;
        while (*p_ && *p_ != '"') {
            char c = *p_++;
            if (c != '\\') { out += c; continue; }
            char e = *p_++;
            switch (e) {
                case 'n': out += '\n'; break;
                case 't': out += '\t'; break;
                case 'r': out += '\r'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'u': {
                    unsigned code = 0;
                    for (int i = 0; i < 4; ++i) {
                        char h = *p_++;
                        code <<= 4;
                        if (h >= '0' && h <= '9') code |= unsigned(h - '0');
                        else if (h >= 'a' && h <= 'f') code |= unsigned(h - 'a' + 10);
                        else if (h >= 'A' && h <= 'F') code |= unsigned(h - 'A' + 10);
                    }
                    if (code < 0x80) {
                        out += char(code);
                    } else if (code < 0x800) {
                        out += char(0xC0 | (code >> 6));
                        out += char(0x80 | (code & 0x3F));
                    } else {
                        out += char(0xE0 | (code >> 12));
                        out += char(0x80 | ((code >> 6) & 0x3F));
                        out += char(0x80 | (code & 0x3F));
                    }
                    break;
                }
                default: out += e; break;
            }
        }
        expect('"');
        return out;
    }

    Value object() {
        Value v;
        v.t = Value::OBJ;
        expect('{');
        skip();
        if (accept('}')) return v;
        for (;;) {
            skip();
            std::string key = string();
            expect(':');
            v.o[key] = value();
            if (accept(',')) continue;
            expect('}');
            break;
        }
        return v;
    }

    Value array() {
        Value v;
        v.t = Value::ARR;
        expect('[');
        skip();
        if (accept(']')) return v;
        for (;;) {
            v.a.push_back(value());
            if (accept(',')) continue;
            expect(']');
            break;
        }
        return v;
    }
};

inline Value parse(const std::string &text) { return Parser(text).parse(); }

}  // namespace tj
