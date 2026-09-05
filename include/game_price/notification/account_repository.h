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
    bool isLoginRateLimited(const std::string& email, const std::string& clientKey) const;
    void recordLoginFailure(const std::string& email, const std::string& clientKey);
    void clearLoginFailures(const std::string& email, const std::string& clientKey);
    std::optional<std::string> createPasswordResetToken(const std::string& email);
    bool resetPassword(const std::string& token, const std::string& passwordHash);
    void enqueueEmail(
        const std::string& recipient,
        const std::string& subject,
        const std::string& body);
    std::string createOAuthState(OAuthProvider provider, std::optional<std::int64_t> linkUserId);
    std::optional<std::int64_t> consumeOAuthState(
        OAuthProvider provider, const std::string& state);
    std::optional<UserAccount> findUserByExternalIdentity(
        OAuthProvider provider, const std::string& providerUserId) const;
    ExternalIdentity addExternalIdentity(std::int64_t userId, const OAuthProfile& profile);
    std::vector<ExternalIdentity> findExternalIdentities(std::int64_t userId) const;
    void deleteExternalIdentity(std::int64_t userId, std::int64_t identityId);
    AlertRule addRule(std::int64_t userId, const std::string& gameId,
                      AlertRuleType type, std::optional<std::int64_t> targetPrice,
                      std::optional<Platform> platform = std::nullopt);
    std::vector<AlertRule> findRules(std::int64_t userId) const;
    bool deleteRule(std::int64_t userId, std::int64_t ruleId);
    std::vector<Notification> findNotifications(std::int64_t userId) const;
    bool markNotificationRead(std::int64_t userId, std::int64_t notificationId);
    bool addFavoriteGame(std::int64_t userId, const std::string& gameId);
    std::vector<std::string> findFavoriteGameIds(std::int64_t userId) const;
    bool deleteFavoriteGame(std::int64_t userId, const std::string& gameId);
    UserPreferences findPreferences(std::int64_t userId) const;
    UserPreferences updatePreferences(
        std::int64_t userId,
        const UserPreferences& preferences);
    bool deleteUser(std::int64_t userId);
    Database& database() const noexcept;
private:
    Database& database_;
};

}  // namespace game_price
