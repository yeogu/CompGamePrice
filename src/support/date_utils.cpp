#include "game_price/support/date_utils.h"

#include <cctype>

namespace game_price {
namespace {

bool isLeapYear(int year) {
    return year % 400 == 0 || (year % 4 == 0 && year % 100 != 0);
}

}  // namespace

bool isIsoDate(const std::string& value) {
    if (value.size() != 10 || value[4] != '-' || value[7] != '-') return false;
    for (std::size_t index = 0; index < value.size(); ++index) {
        if (index == 4 || index == 7) continue;
        if (!std::isdigit(static_cast<unsigned char>(value[index]))) return false;
    }

    const int year = std::stoi(value.substr(0, 4));
    const int month = std::stoi(value.substr(5, 2));
    const int day = std::stoi(value.substr(8, 2));
    if (year == 0 || month < 1 || month > 12 || day < 1) return false;
    const int daysPerMonth[] = {
        31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31};
    return day <= daysPerMonth[month - 1];
}

bool isUtcTimestamp(const std::string& value) {
    if (value.size() != 24 || value[10] != 'T' || value[13] != ':' ||
        value[16] != ':' || value[19] != '.' || value[23] != 'Z' ||
        !isIsoDate(value.substr(0, 10))) {
        return false;
    }
    for (const std::size_t index : {11U, 12U, 14U, 15U, 17U, 18U, 20U, 21U, 22U}) {
        if (!std::isdigit(static_cast<unsigned char>(value[index]))) return false;
    }
    const int hour = std::stoi(value.substr(11, 2));
    const int minute = std::stoi(value.substr(14, 2));
    const int second = std::stoi(value.substr(17, 2));
    return hour <= 23 && minute <= 59 && second <= 59;
}

}  // namespace game_price
