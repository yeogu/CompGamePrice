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

}  // namespace game_price
