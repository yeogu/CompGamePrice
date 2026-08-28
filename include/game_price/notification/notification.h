#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace game_price {

enum class AlertRuleType { PriceDrop, BelowTargetPrice, NewHistoricalLow, BelowAverage };
enum class OAuthProvider { Google, Kakao, Naver };

struct UserAccount { std::int64_t id{}; std::string email; };
struct ExternalIdentity {
    std::int64_t id{};
    std::int64_t userId{};
    OAuthProvider provider{OAuthProvider::Google};
    std::string providerUserId;
    std::optional<std::string> email;
};
struct OAuthProfile {
    OAuthProvider provider{OAuthProvider::Google};
    std::string providerUserId;
    std::optional<std::string> email;
};
struct AlertRule {
    std::int64_t id{};
    std::int64_t userId{};
    std::string gameId;
    AlertRuleType type{AlertRuleType::PriceDrop};
    std::optional<std::int64_t> targetPriceMinor;
    bool active{true};
};
struct Notification {
    std::int64_t id{};
    std::int64_t userId{};
    std::int64_t ruleId{};
    std::string gameId;
    std::string store;
    std::string productId;
    std::int64_t priceMinor{};
    std::string currency;
    std::string message;
    std::string createdAt;
    bool read{false};
};

std::string toString(AlertRuleType type);
AlertRuleType alertRuleTypeFromString(const std::string& value);
std::string toString(OAuthProvider provider);
OAuthProvider oauthProviderFromString(const std::string& value);

}  // namespace game_price
