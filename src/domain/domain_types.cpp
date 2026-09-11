#include "game_price/domain/domain_types.h"

namespace game_price {

std::string toString(Store store) {
    switch (store) {
        case Store::Steam: return "Steam";
        case Store::EpicGamesStore: return "Epic Games Store";
        case Store::NintendoEShop: return "Nintendo eShop";
        case Store::PlayStationStore: return "PlayStation Store";
        case Store::MicrosoftStore: return "Microsoft Store";
        case Store::GooglePlay: return "Google Play";
        case Store::AppleAppStore: return "Apple App Store";
        case Store::UbisoftStore: return "Ubisoft Store";
        case Store::GOG: return "GOG";
        case Store::MetaQuestStore: return "Meta Quest Store";
        case Store::EAApp: return "EA app";
        case Store::BattleNet: return "Battle.net";
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
        case Platform::NintendoSwitch: return "Nintendo Switch";
        case Platform::NintendoSwitch2: return "Nintendo Switch 2";
        case Platform::PlayStation4: return "PlayStation 4";
        case Platform::PlayStation5: return "PlayStation 5";
        case Platform::XboxOne: return "Xbox One";
        case Platform::XboxSeries: return "Xbox Series X|S";
        case Platform::MetaQuest: return "Meta Quest";
    }
    return "Unknown Platform";
}

std::string toString(Currency currency) {
    switch (currency) {
        case Currency::KRW: return "KRW";
        case Currency::USD: return "USD";
        case Currency::EUR: return "EUR";
        case Currency::GBP: return "GBP";
        case Currency::JPY: return "JPY";
    }
    return "Unknown Currency";
}

std::string toString(Region region) {
    switch (region) {
        case Region::KR: return "KR";
    }
    return "Unknown Region";
}

std::string toString(GameEdition edition) {
    switch (edition) {
        case GameEdition::Standard: return "Standard";
        case GameEdition::Deluxe: return "Deluxe";
        case GameEdition::Switch2Edition: return "Switch2Edition";
    }
    return "Unknown Edition";
}

std::string toString(OfferType offerType) {
    switch (offerType) {
        case OfferType::BaseGame: return "BaseGame";
        case OfferType::DLC: return "DLC";
        case OfferType::Bundle: return "Bundle";
        case OfferType::Subscription: return "Subscription";
        case OfferType::UpgradePack: return "UpgradePack";
    }
    return "Unknown Offer Type";
}

std::string toString(CompatibilityStatus status) {
    switch (status) {
        case CompatibilityStatus::Native: return "Native";
        case CompatibilityStatus::Compatible: return "Compatible";
        case CompatibilityStatus::Limited: return "Limited";
        case CompatibilityStatus::Unsupported: return "Unsupported";
        case CompatibilityStatus::Unknown: return "Unknown";
    }
    return "Unknown";
}

std::string toString(PriceFreshness freshness) {
    switch (freshness) {
        case PriceFreshness::Fresh: return "Fresh";
        case PriceFreshness::Stale: return "Stale";
        case PriceFreshness::Unknown: return "Unknown";
    }
    return "Unknown";
}

}  // namespace game_price
