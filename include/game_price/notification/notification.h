#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include "game_price/domain/domain_types.h"

namespace game_price {

enum class AlertRuleType { PriceDrop, BelowTargetPrice, NewHistoricalLow, BelowAverage };
enum class OAuthProvider { Google, Kakao, Naver };
enum class UserRole { User, Admin };

struct UserAccount {
    std::int64_t id{};
    std::string email;
    UserRole role{UserRole::User};
    bool active{true};
};
struct AdminUserSummary {
    std::int64_t id{};
    std::string email;
    UserRole role{UserRole::User};
    bool active{true};
    std::string createdAt;
    std::optional<std::string> lastLoginAt;
    std::optional<std::string> suspensionReason;
    std::int64_t favoriteCount{};
    std::int64_t alertCount{};
};
struct AdminUserAudit {
    std::int64_t id{};
    std::int64_t actorUserId{};
    std::int64_t targetUserId{};
    std::string actorEmail;
    std::string targetEmail;
    std::string action;
    std::optional<std::string> detail;
    std::string createdAt;
};
struct UserPreferences {
    bool emailNotificationsEnabled{true};
    std::string region{"KR"};
    std::string currency{"KRW"};
};
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
    std::optional<Platform> platform;
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
std::string toString(UserRole role);
UserRole userRoleFromString(const std::string& value);

}  // namespace game_price
