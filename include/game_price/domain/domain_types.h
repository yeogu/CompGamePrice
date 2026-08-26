#pragma once

#include <string>

namespace game_price {

enum class Store {
    Steam,
    EpicGamesStore,
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

enum class Region {
    KR
};

enum class GameEdition {
    Standard,
    Deluxe
};

enum class OfferType {
    BaseGame,
    DLC,
    Bundle,
    Subscription
};

std::string toString(Store store);
std::string toString(Platform platform);
std::string toString(Currency currency);
std::string toString(Region region);
std::string toString(GameEdition edition);
std::string toString(OfferType offerType);

}  // namespace game_price
