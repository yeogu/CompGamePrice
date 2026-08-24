#pragma once

#include <string>

namespace game_price {

enum class Store {
    Steam,
    GooglePlay,
    AppleAppStore
};

enum class Platform {
    Windows,
    MacOS,
    Linux,
    Android,
    IOS,
    IPadOS
};

enum class Currency {
    KRW
};

std::string toString(Store store);
std::string toString(Platform platform);
std::string toString(Currency currency);

}  // namespace game_price
