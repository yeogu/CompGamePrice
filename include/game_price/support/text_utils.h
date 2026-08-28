#pragma once

#include <algorithm>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace game_price {

inline std::string trim(const std::string& value) {
    const auto first = std::find_if_not(value.begin(), value.end(), [](unsigned char c) {
        return std::isspace(c) != 0;
    });
    const auto last = std::find_if_not(value.rbegin(), value.rend(), [](unsigned char c) {
        return std::isspace(c) != 0;
    }).base();
    return first < last ? std::string(first, last) : std::string{};
}

inline std::string normalizeName(const std::string& value) {
    std::string result;
    bool previousWasSpace = false;
    for (unsigned char c : trim(value)) {
        if (std::isspace(c) != 0) {
            if (!previousWasSpace) {
                result.push_back(' ');
                previousWasSpace = true;
            }
        } else {
            result.push_back(static_cast<char>(std::tolower(c)));
            previousWasSpace = false;
        }
    }
    return result;
}

inline std::vector<std::string> split(const std::string& value, char delimiter) {
    std::vector<std::string> fields;
    std::stringstream stream(value);
    std::string field;
    while (std::getline(stream, field, delimiter)) {
        fields.push_back(trim(field));
    }
    return fields;
}

inline bool parseBool(const std::string& value) {
    if (value == "true" || value == "1" || value == "yes") return true;
    if (value == "false" || value == "0" || value == "no") return false;
    throw std::invalid_argument("Invalid boolean value: " + value);
}

}  // namespace game_price
