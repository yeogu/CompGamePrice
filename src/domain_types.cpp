#include "game_price/domain_types.h"

namespace game_price {

std::string toString(Store store) {
    switch (store) {
        case Store::Steam: return "Steam";
        case Store::GooglePlay: return "Google Play";
        case Store::AppleAppStore: return "Apple App Store";
    }
    return "Unknown Store";
}

std::string toString(Platform platform) {
    switch (platform) {
        case Platform::Windows: return "Windows";
        case Platform::MacOS: return "macOS";
        case Platform::Linux: return "Linux";
        case Platform::Android: return "Android";
        case Platform::IOS: return "iOS";
        case Platform::IPadOS: return "iPadOS";
    }
    return "Unknown Platform";
}

std::string toString(Currency currency) {
    switch (currency) {
        case Currency::KRW: return "KRW";
    }
    return "Unknown Currency";
}

}  // namespace game_price
