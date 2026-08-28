#include "game_price/notification/notification.h"

#include <stdexcept>

namespace game_price {
std::string toString(AlertRuleType type) {
    switch (type) {
        case AlertRuleType::PriceDrop: return "PriceDrop";
        case AlertRuleType::BelowTargetPrice: return "BelowTargetPrice";
        case AlertRuleType::NewHistoricalLow: return "NewHistoricalLow";
        case AlertRuleType::BelowAverage: return "BelowAverage";
    }
    return "Unknown";
}
AlertRuleType alertRuleTypeFromString(const std::string& value) {
    if (value == "PriceDrop") return AlertRuleType::PriceDrop;
    if (value == "BelowTargetPrice") return AlertRuleType::BelowTargetPrice;
    if (value == "NewHistoricalLow") return AlertRuleType::NewHistoricalLow;
    if (value == "BelowAverage") return AlertRuleType::BelowAverage;
    throw std::invalid_argument("unsupported alert rule type");
}
std::string toString(OAuthProvider provider) {
    switch (provider) {
        case OAuthProvider::Google: return "Google";
        case OAuthProvider::Kakao: return "Kakao";
        case OAuthProvider::Naver: return "Naver";
    }
    return "Unknown";
}
OAuthProvider oauthProviderFromString(const std::string& value) {
    if (value == "Google" || value == "google") return OAuthProvider::Google;
    if (value == "Kakao" || value == "kakao") return OAuthProvider::Kakao;
    if (value == "Naver" || value == "naver") return OAuthProvider::Naver;
    throw std::invalid_argument("unsupported OAuth provider");
}
}  // namespace game_price
