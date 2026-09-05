#include "game_price/notification/account_repository.h"

#include <openssl/rand.h>
#include <openssl/sha.h>
#include <sqlite3.h>

#include <array>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace game_price {
namespace {
class Statement {
public:
    Statement(sqlite3* db, const char* sql) : db_(db) {
        if (sqlite3_prepare_v2(db, sql, -1, &value_, nullptr) != SQLITE_OK)
            throw std::runtime_error(sqlite3_errmsg(db));
    }
    ~Statement() { sqlite3_finalize(value_); }
    sqlite3_stmt* get() const { return value_; }
    bool next() { return sqlite3_step(value_) == SQLITE_ROW; }
    void execute() {
        if (sqlite3_step(value_) != SQLITE_DONE) throw std::runtime_error(sqlite3_errmsg(db_));
    }
private: sqlite3* db_{}; sqlite3_stmt* value_{};
};
void bindText(sqlite3_stmt* value, int index, const std::string& text) {
    sqlite3_bind_text(value, index, text.c_str(), -1, SQLITE_TRANSIENT);
}
std::string text(sqlite3_stmt* value, int index) {
    const auto* result = sqlite3_column_text(value, index);
    return result ? reinterpret_cast<const char*>(result) : "";
}
std::string randomToken() {
    std::array<unsigned char, 32> bytes{};
    if (RAND_bytes(bytes.data(), static_cast<int>(bytes.size())) != 1)
        throw std::runtime_error("Cannot generate secure session token");
    std::ostringstream output;
    for (const auto byte : bytes) output << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(byte);
    return output.str();
}
std::string sessionTokenHash(const std::string& token) {
    std::array<unsigned char,SHA256_DIGEST_LENGTH> digest{};
    SHA256(reinterpret_cast<const unsigned char*>(token.data()),token.size(),digest.data());
    std::ostringstream output;
    for(const auto byte:digest)output<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<int>(byte);
    return output.str();
}
AlertRule readRule(sqlite3_stmt* row) {
    const auto platformName = sqlite3_column_type(row, 5) == SQLITE_NULL
        ? std::string{}
        : text(row, 5);
    std::optional<Platform> platform;
    if (platformName == "Windows") {
        platform = Platform::Windows;
    } else if (platformName == "macOS") {
        platform = Platform::MacOS;
    } else if (platformName == "Linux") {
        platform = Platform::Linux;
    } else if (platformName == "Android") {
        platform = Platform::Android;
    } else if (platformName == "iOS") {
        platform = Platform::IOS;
    } else if (platformName == "iPadOS") {
        platform = Platform::IPadOS;
    } else if (platformName == "Nintendo Switch") {
        platform = Platform::NintendoSwitch;
    } else if (platformName == "Nintendo Switch 2") {
        platform = Platform::NintendoSwitch2;
    } else if (platformName == "PlayStation 4") {
        platform = Platform::PlayStation4;
    } else if (platformName == "PlayStation 5") {
        platform = Platform::PlayStation5;
    } else if (platformName == "Xbox One") {
        platform = Platform::XboxOne;
    } else if (platformName == "Xbox Series X|S") {
        platform = Platform::XboxSeries;
    } else if (!platformName.empty()) {
        throw std::runtime_error("Unknown alert platform in database");
    }
    return AlertRule{sqlite3_column_int64(row, 0), sqlite3_column_int64(row, 1),
        text(row, 2), alertRuleTypeFromString(text(row, 3)),
        sqlite3_column_type(row, 4) == SQLITE_NULL ? std::nullopt :
            std::optional<std::int64_t>{sqlite3_column_int64(row, 4)},
        platform,
        sqlite3_column_int(row, 6) != 0};
}
}  // namespace

AccountRepository::AccountRepository(Database& database) : database_(database) {}

UserAccount AccountRepository::createUser(const std::string& email, const std::string& hash) {
    Statement statement(database_.handle(),
        "INSERT INTO users(email,password_hash) VALUES(?,?);");
    bindText(statement.get(), 1, email); bindText(statement.get(), 2, hash);
    statement.execute();
    return UserAccount{
        sqlite3_last_insert_rowid(database_.handle()),
        email,
        UserRole::User,
    };
}
std::optional<std::pair<UserAccount, std::string>> AccountRepository::findUserByEmail(
    const std::string& email) const {
    Statement statement(database_.handle(),
        "SELECT id,email,password_hash,role FROM users WHERE email=?;");
    bindText(statement.get(), 1, email);
    if (!statement.next()) return std::nullopt;
    return std::pair<UserAccount, std::string>{
        UserAccount{
            sqlite3_column_int64(statement.get(), 0),
            text(statement.get(), 1),
            userRoleFromString(text(statement.get(), 3)),
        },
        text(statement.get(), 2)};
}
std::string AccountRepository::createSession(std::int64_t userId) {
    const auto token = randomToken();
    Statement statement(database_.handle(), R"sql(
        INSERT INTO user_sessions(token,user_id,created_at,expires_at)
        VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                  strftime('%Y-%m-%dT%H:%M:%fZ','now','+30 days'));
    )sql");
    bindText(statement.get(), 1, sessionTokenHash(token)); sqlite3_bind_int64(statement.get(), 2, userId);
    statement.execute(); return token;
}
std::optional<UserAccount> AccountRepository::findUserBySession(const std::string& token) const {
    Statement statement(database_.handle(), R"sql(
        SELECT u.id,u.email,u.role FROM user_sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token=? AND s.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now');
    )sql");
    bindText(statement.get(), 1, sessionTokenHash(token));
    if (!statement.next()) return std::nullopt;
    return UserAccount{
        sqlite3_column_int64(statement.get(), 0),
        text(statement.get(), 1),
        userRoleFromString(text(statement.get(), 2)),
    };
}
void AccountRepository::deleteSession(const std::string& token) {
    Statement statement(database_.handle(), "DELETE FROM user_sessions WHERE token=?;");
    bindText(statement.get(), 1, sessionTokenHash(token)); statement.execute();
}
bool AccountRepository::isLoginRateLimited(const std::string& email,const std::string& clientKey) const {
    Statement statement(database_.handle(),R"sql(
        SELECT COUNT(*) FROM login_attempts WHERE email=? AND client_key=?
        AND failed_at>=strftime('%Y-%m-%dT%H:%M:%fZ','now','-15 minutes');
    )sql"); bindText(statement.get(),1,email);bindText(statement.get(),2,clientKey);
    return statement.next()&&sqlite3_column_int(statement.get(),0)>=5;
}
void AccountRepository::recordLoginFailure(const std::string& email,const std::string& clientKey) {
    Statement cleanup(database_.handle(),"DELETE FROM login_attempts WHERE failed_at<strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 day');");cleanup.execute();
    Statement statement(database_.handle(),"INSERT INTO login_attempts(email,client_key) VALUES(?,?);");
    bindText(statement.get(),1,email);bindText(statement.get(),2,clientKey);statement.execute();
}
void AccountRepository::clearLoginFailures(const std::string& email,const std::string& clientKey) {
    Statement statement(database_.handle(),"DELETE FROM login_attempts WHERE email=? AND client_key=?;");
    bindText(statement.get(),1,email);bindText(statement.get(),2,clientKey);statement.execute();
}
std::optional<std::string> AccountRepository::createPasswordResetToken(
    const std::string& email) {
    const auto user = findUserByEmail(email);
    if (!user) {
        return std::nullopt;
    }
    Statement recent(database_.handle(), R"sql(
        SELECT 1 FROM password_reset_tokens
        WHERE user_id=? AND created_at>strftime('%Y-%m-%dT%H:%M:%fZ','now','-1 minute')
        LIMIT 1;
    )sql");
    sqlite3_bind_int64(recent.get(), 1, user->first.id);
    if (recent.next()) {
        return std::nullopt;
    }
    const auto token = randomToken();
    database_.execute("BEGIN IMMEDIATE;");
    try {
        Statement cleanup(database_.handle(), R"sql(
            DELETE FROM password_reset_tokens
            WHERE user_id=? OR expires_at<=strftime('%Y-%m-%dT%H:%M:%fZ','now');
        )sql");
        sqlite3_bind_int64(cleanup.get(), 1, user->first.id);
        cleanup.execute();
        Statement insert(database_.handle(), R"sql(
            INSERT INTO password_reset_tokens(token_hash,user_id,expires_at)
            VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now','+30 minutes'));
        )sql");
        bindText(insert.get(), 1, sessionTokenHash(token));
        sqlite3_bind_int64(insert.get(), 2, user->first.id);
        insert.execute();
        database_.execute("COMMIT;");
    } catch (...) {
        try {
            database_.execute("ROLLBACK;");
        } catch (...) {
        }
        throw;
    }
    return token;
}
bool AccountRepository::resetPassword(
    const std::string& token,
    const std::string& passwordHash) {
    database_.execute("BEGIN IMMEDIATE;");
    try {
        Statement select(database_.handle(), R"sql(
            SELECT user_id FROM password_reset_tokens
            WHERE token_hash=? AND used_at IS NULL
              AND expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now');
        )sql");
        bindText(select.get(), 1, sessionTokenHash(token));
        if (!select.next()) {
            database_.execute("ROLLBACK;");
            return false;
        }
        const auto userId = sqlite3_column_int64(select.get(), 0);
        Statement updateUser(
            database_.handle(),
            "UPDATE users SET password_hash=? WHERE id=?;");
        bindText(updateUser.get(), 1, passwordHash);
        sqlite3_bind_int64(updateUser.get(), 2, userId);
        updateUser.execute();
        Statement invalidateTokens(database_.handle(), R"sql(
            UPDATE password_reset_tokens
            SET used_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE user_id=? AND used_at IS NULL;
        )sql");
        sqlite3_bind_int64(invalidateTokens.get(), 1, userId);
        invalidateTokens.execute();
        Statement deleteSessions(
            database_.handle(),
            "DELETE FROM user_sessions WHERE user_id=?;");
        sqlite3_bind_int64(deleteSessions.get(), 1, userId);
        deleteSessions.execute();
        database_.execute("COMMIT;");
        return true;
    } catch (...) {
        try {
            database_.execute("ROLLBACK;");
        } catch (...) {
        }
        throw;
    }
}
void AccountRepository::enqueueEmail(
    const std::string& recipient,
    const std::string& subject,
    const std::string& body) {
    Statement statement(database_.handle(), R"sql(
        INSERT INTO email_outbox(recipient,subject,body) VALUES(?,?,?);
    )sql");
    bindText(statement.get(), 1, recipient);
    bindText(statement.get(), 2, subject);
    bindText(statement.get(), 3, body);
    statement.execute();
}
std::string AccountRepository::createOAuthState(
    OAuthProvider provider, std::optional<std::int64_t> linkUserId) {
    const auto state = randomToken();
    Statement statement(database_.handle(), R"sql(
        INSERT INTO oauth_states(state,provider,link_user_id,expires_at)
        VALUES(?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now','+10 minutes'));
    )sql");
    bindText(statement.get(),1,state); bindText(statement.get(),2,toString(provider));
    if(linkUserId) sqlite3_bind_int64(statement.get(),3,*linkUserId); else sqlite3_bind_null(statement.get(),3);
    statement.execute(); return state;
}
std::optional<std::int64_t> AccountRepository::consumeOAuthState(
    OAuthProvider provider, const std::string& state) {
    database_.execute("BEGIN IMMEDIATE;");
    try {
        Statement select(database_.handle(), R"sql(
            SELECT link_user_id FROM oauth_states
            WHERE state=? AND provider=? AND expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now');
        )sql");
        bindText(select.get(),1,state); bindText(select.get(),2,toString(provider));
        if(!select.next()) { database_.execute("ROLLBACK;"); return std::nullopt; }
        const bool hasUser=sqlite3_column_type(select.get(),0)!=SQLITE_NULL;
        const auto userId=hasUser ? std::optional<std::int64_t>{sqlite3_column_int64(select.get(),0)} : std::optional<std::int64_t>{0};
        Statement remove(database_.handle(),"DELETE FROM oauth_states WHERE state=?;");
        bindText(remove.get(),1,state); remove.execute(); database_.execute("COMMIT;"); return userId;
    } catch (...) { try { database_.execute("ROLLBACK;"); } catch (...) {} throw; }
}
std::optional<UserAccount> AccountRepository::findUserByExternalIdentity(
    OAuthProvider provider, const std::string& providerUserId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT u.id,u.email,u.role FROM external_identities e JOIN users u ON u.id=e.user_id
        WHERE e.provider=? AND e.provider_user_id=?;
    )sql");
    bindText(statement.get(),1,toString(provider)); bindText(statement.get(),2,providerUserId);
    if(!statement.next()) return std::nullopt;
    return UserAccount{
        sqlite3_column_int64(statement.get(), 0),
        text(statement.get(), 1),
        userRoleFromString(text(statement.get(), 2)),
    };
}
ExternalIdentity AccountRepository::addExternalIdentity(
    std::int64_t userId, const OAuthProfile& profile) {
    Statement statement(database_.handle(), R"sql(
        INSERT INTO external_identities(user_id,provider,provider_user_id,email)
        VALUES(?,?,?,?);
    )sql");
    sqlite3_bind_int64(statement.get(),1,userId); bindText(statement.get(),2,toString(profile.provider));
    bindText(statement.get(),3,profile.providerUserId);
    if(profile.email) bindText(statement.get(),4,*profile.email); else sqlite3_bind_null(statement.get(),4);
    statement.execute();
    return ExternalIdentity{sqlite3_last_insert_rowid(database_.handle()),userId,
        profile.provider,profile.providerUserId,profile.email};
}
std::vector<ExternalIdentity> AccountRepository::findExternalIdentities(std::int64_t userId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT id,user_id,provider,provider_user_id,email
        FROM external_identities WHERE user_id=? ORDER BY id;
    )sql"); sqlite3_bind_int64(statement.get(),1,userId); std::vector<ExternalIdentity> result;
    while(statement.next()) result.push_back(ExternalIdentity{
        sqlite3_column_int64(statement.get(),0),sqlite3_column_int64(statement.get(),1),
        oauthProviderFromString(text(statement.get(),2)),text(statement.get(),3),
        sqlite3_column_type(statement.get(),4)==SQLITE_NULL?std::nullopt:std::optional<std::string>{text(statement.get(),4)}});
    return result;
}
void AccountRepository::deleteExternalIdentity(std::int64_t userId,std::int64_t identityId) {
    Statement guard(database_.handle(), R"sql(
        SELECT u.password_hash,(SELECT COUNT(*) FROM external_identities WHERE user_id=u.id)
        FROM users u WHERE u.id=?;
    )sql"); sqlite3_bind_int64(guard.get(),1,userId);
    if(!guard.next()) throw std::invalid_argument("user not found");
    if(text(guard.get(),0)=="!social" && sqlite3_column_int(guard.get(),1)<=1)
        throw std::invalid_argument("cannot remove the only login method");
    Statement statement(database_.handle(),"DELETE FROM external_identities WHERE id=? AND user_id=?;");
    sqlite3_bind_int64(statement.get(),1,identityId); sqlite3_bind_int64(statement.get(),2,userId); statement.execute();
}
AlertRule AccountRepository::addRule(std::int64_t userId, const std::string& gameId,
    AlertRuleType type, std::optional<std::int64_t> targetPrice,std::optional<Platform> platform) {
    if ((type == AlertRuleType::BelowTargetPrice) != targetPrice.has_value() ||
        (targetPrice && (*targetPrice <= 0 || *targetPrice > 1000000000)))
        throw std::invalid_argument("target price must be between 1 and 1000000000 KRW");
    Statement duplicate(database_.handle(),R"sql(
        SELECT 1 FROM alert_rules WHERE user_id=? AND game_id=? AND rule_type=?
        AND COALESCE(platform,'')=COALESCE(?,'')
        AND COALESCE(target_price_minor,-1)=COALESCE(?,-1);
    )sql");
    sqlite3_bind_int64(duplicate.get(),1,userId);bindText(duplicate.get(),2,gameId);bindText(duplicate.get(),3,toString(type));
    if(platform)bindText(duplicate.get(),4,toString(*platform));else sqlite3_bind_null(duplicate.get(),4);
    if(targetPrice)sqlite3_bind_int64(duplicate.get(),5,*targetPrice);else sqlite3_bind_null(duplicate.get(),5);
    if(duplicate.next())throw std::invalid_argument("alert rule already exists");
    Statement statement(database_.handle(), R"sql(
        INSERT INTO alert_rules(user_id,game_id,rule_type,target_price_minor,platform)
        VALUES(?,?,?,?,?);
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId); bindText(statement.get(), 2, gameId);
    bindText(statement.get(), 3, toString(type));
    if (targetPrice) sqlite3_bind_int64(statement.get(), 4, *targetPrice);
    else sqlite3_bind_null(statement.get(), 4);
    if(platform)bindText(statement.get(),5,toString(*platform));else sqlite3_bind_null(statement.get(),5);
    statement.execute();
    return AlertRule{sqlite3_last_insert_rowid(database_.handle()), userId, gameId,
                     type, targetPrice,platform,true};
}
std::vector<AlertRule> AccountRepository::findRules(std::int64_t userId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT id,user_id,game_id,rule_type,target_price_minor,platform,active
        FROM alert_rules WHERE user_id=? ORDER BY id DESC;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    std::vector<AlertRule> result; while (statement.next()) result.push_back(readRule(statement.get()));
    return result;
}
bool AccountRepository::deleteRule(std::int64_t userId, std::int64_t ruleId) {
    Statement statement(database_.handle(), "DELETE FROM alert_rules WHERE id=? AND user_id=?;");
    sqlite3_bind_int64(statement.get(), 1, ruleId); sqlite3_bind_int64(statement.get(), 2, userId);
    statement.execute();return sqlite3_changes(database_.handle())>0;
}
std::vector<Notification> AccountRepository::findNotifications(std::int64_t userId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT id,user_id,rule_id,game_id,store,external_product_id,price_minor,
               currency,message,created_at,read
        FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId); std::vector<Notification> result;
    while (statement.next()) result.push_back(Notification{
        sqlite3_column_int64(statement.get(),0), sqlite3_column_int64(statement.get(),1),
        sqlite3_column_int64(statement.get(),2), text(statement.get(),3), text(statement.get(),4),
        text(statement.get(),5), sqlite3_column_int64(statement.get(),6), text(statement.get(),7),
        text(statement.get(),8), text(statement.get(),9), sqlite3_column_int(statement.get(),10)!=0});
    return result;
}
bool AccountRepository::markNotificationRead(std::int64_t userId, std::int64_t id) {
    Statement statement(database_.handle(), "UPDATE notifications SET read=1 WHERE id=? AND user_id=?;");
    sqlite3_bind_int64(statement.get(),1,id); sqlite3_bind_int64(statement.get(),2,userId); statement.execute();return sqlite3_changes(database_.handle())>0;
}

bool AccountRepository::addFavoriteGame(
    std::int64_t userId,
    const std::string& gameId) {
    Statement statement(database_.handle(), R"sql(
        INSERT OR IGNORE INTO favorite_games(user_id, game_id)
        VALUES(?, ?);
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    bindText(statement.get(), 2, gameId);
    statement.execute();
    return sqlite3_changes(database_.handle()) > 0;
}

std::vector<std::string> AccountRepository::findFavoriteGameIds(
    std::int64_t userId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT game_id
        FROM favorite_games
        WHERE user_id = ?
        ORDER BY created_at DESC, game_id ASC;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    std::vector<std::string> result;
    while (statement.next()) {
        result.push_back(text(statement.get(), 0));
    }
    return result;
}

bool AccountRepository::deleteFavoriteGame(
    std::int64_t userId,
    const std::string& gameId) {
    Statement statement(database_.handle(), R"sql(
        DELETE FROM favorite_games
        WHERE user_id = ? AND game_id = ?;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    bindText(statement.get(), 2, gameId);
    statement.execute();
    return sqlite3_changes(database_.handle()) > 0;
}

UserPreferences AccountRepository::findPreferences(std::int64_t userId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT email_notifications_enabled, region, currency
        FROM user_preferences
        WHERE user_id = ?;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    if (!statement.next()) {
        return UserPreferences{};
    }
    return UserPreferences{
        sqlite3_column_int(statement.get(), 0) != 0,
        text(statement.get(), 1),
        text(statement.get(), 2)};
}

UserPreferences AccountRepository::updatePreferences(
    std::int64_t userId,
    const UserPreferences& preferences) {
    if (preferences.region != "KR" || preferences.currency != "KRW") {
        throw std::invalid_argument("only KR and KRW are supported");
    }
    Statement statement(database_.handle(), R"sql(
        INSERT INTO user_preferences(
            user_id, email_notifications_enabled, region, currency)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            email_notifications_enabled = excluded.email_notifications_enabled,
            region = excluded.region,
            currency = excluded.currency;
    )sql");
    sqlite3_bind_int64(statement.get(), 1, userId);
    sqlite3_bind_int(statement.get(), 2, preferences.emailNotificationsEnabled ? 1 : 0);
    bindText(statement.get(), 3, preferences.region);
    bindText(statement.get(), 4, preferences.currency);
    statement.execute();
    return preferences;
}

bool AccountRepository::deleteUser(std::int64_t userId) {
    Statement statement(
        database_.handle(),
        "DELETE FROM users WHERE id=?;");
    sqlite3_bind_int64(statement.get(), 1, userId);
    statement.execute();
    return sqlite3_changes(database_.handle()) > 0;
}

Database& AccountRepository::database() const noexcept { return database_; }

}  // namespace game_price
