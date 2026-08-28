#pragma once

#include "game_price/notification/notification.h"
#include "game_price/persistence/database.h"

#include <optional>
#include <string>
#include <vector>

namespace game_price {

class AccountRepository {
public:
    explicit AccountRepository(Database& database);
    UserAccount createUser(const std::string& email, const std::string& passwordHash);
    std::optional<std::pair<UserAccount, std::string>> findUserByEmail(
        const std::string& email) const;
    std::string createSession(std::int64_t userId);
    std::optional<UserAccount> findUserBySession(const std::string& token) const;
    void deleteSession(const std::string& token);
    std::string createOAuthState(OAuthProvider provider, std::optional<std::int64_t> linkUserId);
    std::optional<std::int64_t> consumeOAuthState(
        OAuthProvider provider, const std::string& state);
    std::optional<UserAccount> findUserByExternalIdentity(
        OAuthProvider provider, const std::string& providerUserId) const;
    ExternalIdentity addExternalIdentity(std::int64_t userId, const OAuthProfile& profile);
    std::vector<ExternalIdentity> findExternalIdentities(std::int64_t userId) const;
    void deleteExternalIdentity(std::int64_t userId, std::int64_t identityId);
    AlertRule addRule(std::int64_t userId, const std::string& gameId,
                      AlertRuleType type, std::optional<std::int64_t> targetPrice);
    std::vector<AlertRule> findRules(std::int64_t userId) const;
    void deleteRule(std::int64_t userId, std::int64_t ruleId);
    std::vector<Notification> findNotifications(std::int64_t userId) const;
    void markNotificationRead(std::int64_t userId, std::int64_t notificationId);
    Database& database() const noexcept;
private:
    Database& database_;
};

}  // namespace game_price
