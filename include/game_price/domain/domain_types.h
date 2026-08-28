#pragma once

#include <string>

namespace game_price {

enum class Store {
    Steam,
    EpicGamesStore,
    NintendoEShop,
    GooglePlay,
    AppleAppStore
};

enum class Platform {
    Windows,
    MacOS,
    Linux,
    Android,
    IOS,
    IPadOS,
    NintendoSwitch,
    NintendoSwitch2
};

enum class Currency {
    KRW
};

enum class Region {
    KR
};

enum class GameEdition {
    Standard,
    Deluxe,
    Switch2Edition
};

enum class OfferType {
    BaseGame,
    DLC,
    Bundle,
    Subscription,
    UpgradePack
};

enum class CompatibilityStatus {
    Native,
    Compatible,
    Limited,
    Unsupported,
    Unknown
};

enum class PriceFreshness {
    Fresh,
    Stale,
    Unknown
};

struct PlatformCompatibility {
    Platform platform;
    CompatibilityStatus status{CompatibilityStatus::Unknown};
};

std::string toString(Store store);
std::string toString(Platform platform);
std::string toString(Currency currency);
std::string toString(Region region);
std::string toString(GameEdition edition);
std::string toString(OfferType offerType);
std::string toString(CompatibilityStatus status);
std::string toString(PriceFreshness freshness);

}  // namespace game_price
