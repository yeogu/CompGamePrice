#pragma once

#include <string>

namespace game_price {

bool isIsoDate(const std::string& value);
bool isUtcTimestamp(const std::string& value);

}  // namespace game_price
