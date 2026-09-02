#include "game_price/persistence/store_product_repository.h"

#include "game_price/domain/domain_types.h"
#include "game_price/domain/store_product_validator.h"
#include "game_price/support/date_utils.h"

#include <sqlite3.h>

#include <cstdlib>
#include <stdexcept>
#include <string>

namespace game_price {
namespace {

class Statement {
public:
    Statement(sqlite3* database, const char* sql) {
        if (sqlite3_prepare_v2(database, sql, -1, &statement_, nullptr) != SQLITE_OK) {
            throw std::runtime_error("Cannot prepare SQL statement: " +
                                     std::string(sqlite3_errmsg(database)));
        }
    }

    ~Statement() {
        sqlite3_finalize(statement_);
    }

    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;

    sqlite3_stmt* get() const noexcept { return statement_; }

    void execute() {
        if (sqlite3_step(statement_) != SQLITE_DONE) {
            throw std::runtime_error("Cannot execute SQL statement: " +
                                     std::string(sqlite3_errmsg(sqlite3_db_handle(statement_))));
        }
    }

    bool next() {
        const int result = sqlite3_step(statement_);
        if (result == SQLITE_ROW) return true;
        if (result == SQLITE_DONE) return false;
        throw std::runtime_error("Cannot read SQL result: " +
                                 std::string(sqlite3_errmsg(sqlite3_db_handle(statement_))));
    }

private:
    sqlite3_stmt* statement_{nullptr};
};

void bindText(sqlite3_stmt* statement, int index, const std::string& value) {
    if (sqlite3_bind_text(statement, index, value.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        throw std::runtime_error("Cannot bind text value");
    }
}

void bindInt64(sqlite3_stmt* statement, int index, std::int64_t value) {
    if (sqlite3_bind_int64(statement, index, value) != SQLITE_OK) {
        throw std::runtime_error("Cannot bind integer value");
    }
}

void bindOptionalInt64(
    sqlite3_stmt* statement,
    int index,
    const std::optional<std::int64_t>& value) {
    const int result = value
        ? sqlite3_bind_int64(statement, index, *value)
        : sqlite3_bind_null(statement, index);
    if (result != SQLITE_OK) throw std::runtime_error("Cannot bind optional integer value");
}

std::string columnText(sqlite3_stmt* statement, int index) {
    const auto* text = sqlite3_column_text(statement, index);
    if (!text) {
        throw std::runtime_error("Unexpected NULL text column");
    }
    return reinterpret_cast<const char*>(text);
}

Store parseStore(const std::string& value) {
    if (value == "Steam") return Store::Steam;
    if (value == "Epic Games Store") return Store::EpicGamesStore;
    if (value == "Nintendo eShop") return Store::NintendoEShop;
    if (value == "Google Play") return Store::GooglePlay;
    if (value == "Apple App Store") return Store::AppleAppStore;
    throw std::runtime_error("Unknown Store value in database: " + value);
}

Platform parsePlatform(const std::string& value) {
    if (value == "Windows") return Platform::Windows;
    if (value == "macOS") return Platform::MacOS;
    if (value == "Linux") return Platform::Linux;
    if (value == "Android") return Platform::Android;
    if (value == "iOS") return Platform::IOS;
    if (value == "iPadOS") return Platform::IPadOS;
    if (value == "Nintendo Switch") return Platform::NintendoSwitch;
    if (value == "Nintendo Switch 2") return Platform::NintendoSwitch2;
    throw std::runtime_error("Unknown Platform value in database: " + value);
}

Region parseRegion(const std::string& value) {
    if (value == "KR") return Region::KR;
    throw std::runtime_error("Unknown Region value in database: " + value);
}

GameEdition parseEdition(const std::string& value) {
    if (value == "Standard") return GameEdition::Standard;
    if (value == "Deluxe") return GameEdition::Deluxe;
    if (value == "Switch2Edition") return GameEdition::Switch2Edition;
    throw std::runtime_error("Unknown Edition value in database: " + value);
}

OfferType parseOfferType(const std::string& value) {
    if (value == "BaseGame") return OfferType::BaseGame;
    if (value == "DLC") return OfferType::DLC;
    if (value == "Bundle") return OfferType::Bundle;
    if (value == "Subscription") return OfferType::Subscription;
    if (value == "UpgradePack") return OfferType::UpgradePack;
    throw std::runtime_error("Unknown Offer Type value in database: " + value);
}

CompatibilityStatus parseCompatibilityStatus(const std::string& value) {
    if (value == "Native") return CompatibilityStatus::Native;
    if (value == "Compatible") return CompatibilityStatus::Compatible;
    if (value == "Limited") return CompatibilityStatus::Limited;
    if (value == "Unsupported") return CompatibilityStatus::Unsupported;
    if (value == "Unknown") return CompatibilityStatus::Unknown;
    throw std::runtime_error("Unknown compatibility status in database: " + value);
}

Currency parseCurrency(const std::string& value) {
    if (value == "KRW") return Currency::KRW;
    throw std::runtime_error("Unknown Currency value in database: " + value);
}

std::optional<std::int64_t> regularPriceMinor(const StoreProduct& product) {
    if (!product.regularPrice) return std::nullopt;
    if (product.regularPrice->currency != product.currentPrice.currency) {
        throw std::runtime_error("Regular and current prices must use the same currency");
    }
    return product.regularPrice->minorAmount;
}

std::string databaseUtcNow(sqlite3* database) {
    Statement statement(
        database, "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now');");
    if (!statement.next()) {
        throw std::runtime_error("Cannot read the database UTC timestamp");
    }
    return columnText(statement.get(), 0);
}

std::string nextUtcMillisecond(sqlite3* database, const std::string& timestamp) {
    Statement statement(database, R"sql(
        SELECT strftime(
            '%Y-%m-%dT%H:%M:%fZ',
            julianday(?) + (0.001 / 86400.0));
    )sql");
    bindText(statement.get(), 1, timestamp);
    if (!statement.next()) {
        throw std::runtime_error("Cannot advance the database UTC timestamp");
    }
    return columnText(statement.get(), 0);
}

bool observationStateMatches(
    sqlite3_stmt* row,
    const StoreProduct& product,
    const std::optional<std::int64_t>& regularPrice,
    const std::string& currency) {
    const bool storedRegularIsNull =
        sqlite3_column_type(row, 1) == SQLITE_NULL;
    const bool regularMatches = regularPrice
        ? !storedRegularIsNull && sqlite3_column_int64(row, 1) == *regularPrice
        : storedRegularIsNull;
    return sqlite3_column_int64(row, 0) == product.currentPrice.minorAmount &&
        regularMatches &&
        sqlite3_column_int(row, 2) == product.discountPercent &&
        columnText(row, 3) == currency &&
        (sqlite3_column_int(row, 4) != 0) == product.purchasable;
}

bool sameObservationState(
    const PriceObservation& left,
    const PriceObservation& right) {
    return left.price == right.price &&
        left.purchasable == right.purchasable &&
        left.regularPrice == right.regularPrice &&
        left.discountPercent == right.discountPercent;
}

void validatePriceObservation(const PriceObservation& observation) {
    if (!isUtcTimestamp(observation.observedAt)) {
        throw std::invalid_argument("Price observation timestamp must be UTC");
    }
    if (observation.price.currency != Currency::KRW ||
        observation.price.minorAmount < 0 ||
        observation.price.minorAmount > MaximumSupportedPriceMinor) {
        throw std::invalid_argument("Price observation contains an invalid price");
    }
    if (observation.discountPercent < 0 || observation.discountPercent > 100) {
        throw std::invalid_argument("Price observation contains an invalid discount");
    }
    if (observation.discountPercent > 0 && !observation.regularPrice) {
        throw std::invalid_argument(
            "A discounted observation requires a regular price");
    }
    if (observation.regularPrice) {
        if (observation.regularPrice->currency != observation.price.currency ||
            observation.regularPrice->minorAmount < observation.price.minorAmount ||
            observation.regularPrice->minorAmount > MaximumSupportedPriceMinor) {
            throw std::invalid_argument(
                "Price observation contains an invalid regular price");
        }
        const auto regular = observation.regularPrice->minorAmount;
        const int calculatedDiscount = regular == 0
            ? 0
            : static_cast<int>(
                  ((regular - observation.price.minorAmount) * 100 + regular / 2) /
                  regular);
        if (std::abs(calculatedDiscount - observation.discountPercent) > 1) {
            throw std::invalid_argument(
                "Price observation discount does not match its prices");
        }
    }
}

CrawlRunStatus parseCrawlRunStatus(const std::string& value) {
    if (value == "RUNNING") return CrawlRunStatus::Running;
    if (value == "SUCCEEDED") return CrawlRunStatus::Succeeded;
    if (value == "FAILED") return CrawlRunStatus::Failed;
    throw std::runtime_error("Unknown crawl run status in database: " + value);
}

bool tableExists(sqlite3* database, const std::string& table) {
    Statement statement(
        database,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;");
    bindText(statement.get(), 1, table);
    return statement.next();
}

bool tableHasColumn(
    sqlite3* database,
    const std::string& table,
    const std::string& column) {
    const auto query = "PRAGMA table_info(" + table + ");";
    Statement statement(database, query.c_str());
    while (statement.next()) {
        if (columnText(statement.get(), 1) == column) {
            return true;
        }
    }
    return false;
}

}  // namespace

StoreProductRepository::StoreProductRepository(Database& database) : database_(database) {}
Database& StoreProductRepository::database() const noexcept { return database_; }

void StoreProductRepository::initializeSchema() const {
    const int existingVersion = database_.userVersion();
    if (existingVersion > CurrentSchemaVersion) {
        throw std::runtime_error(
            "Database schema version " + std::to_string(existingVersion) +
            " is newer than supported version " +
            std::to_string(CurrentSchemaVersion));
    }
    if (existingVersion == CurrentSchemaVersion) return;
    const auto usersExisted = tableExists(database_.handle(), "users");
    const auto usersHadRole = usersExisted &&
        tableHasColumn(database_.handle(), "users", "role");

    database_.execute("BEGIN IMMEDIATE TRANSACTION;");
    try {
        database_.execute(R"sql(
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS store_products (
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
            regular_price_minor INTEGER CHECK (regular_price_minor >= 0),
            discount_percent INTEGER NOT NULL DEFAULT 0
                CHECK (discount_percent BETWEEN 0 AND 100),
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL CHECK (purchasable IN (0, 1)),
            region TEXT NOT NULL DEFAULT 'KR' CHECK (region IN ('KR')),
            edition TEXT NOT NULL DEFAULT 'Standard'
                CHECK (edition IN ('Standard', 'Deluxe', 'Switch2Edition')),
            offer_type TEXT NOT NULL DEFAULT 'BaseGame'
                CHECK (offer_type IN (
                    'BaseGame', 'DLC', 'Bundle', 'Subscription', 'UpgradePack')),
            PRIMARY KEY (store, external_product_id),
            FOREIGN KEY (game_id) REFERENCES games(id)
        );

        CREATE TABLE IF NOT EXISTS product_platforms (
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            PRIMARY KEY (store, external_product_id, platform),
            FOREIGN KEY (store, external_product_id)
                REFERENCES store_products(store, external_product_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS product_compatibility (
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('Native', 'Compatible', 'Limited', 'Unsupported', 'Unknown')),
            PRIMARY KEY (store, external_product_id, platform),
            FOREIGN KEY (store, external_product_id)
                REFERENCES store_products(store, external_product_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
            regular_price_minor INTEGER CHECK (regular_price_minor >= 0),
            discount_percent INTEGER NOT NULL DEFAULT 0
                CHECK (discount_percent BETWEEN 0 AND 100),
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL CHECK (purchasable IN (0, 1)),
            observed_at TEXT NOT NULL,
            FOREIGN KEY (store, external_product_id)
                REFERENCES store_products(store, external_product_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_product_time
            ON price_history(store, external_product_id, observed_at);

        CREATE TABLE IF NOT EXISTS price_history_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_history_id INTEGER NOT NULL,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            regular_price_minor INTEGER,
            discount_percent INTEGER NOT NULL,
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            quarantined_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
            products_found INTEGER NOT NULL DEFAULT 0 CHECK (products_found >= 0),
            error_message TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS collection_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crawl_run_id INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
            store TEXT NOT NULL,
            game_id TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            rejected_at TEXT NOT NULL DEFAULT
                (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'USER' CHECK(role IN ('USER','ADMIN')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS external_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL CHECK(provider IN ('Google','Kakao','Naver')),
            provider_user_id TEXT NOT NULL,
            email TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(provider, provider_user_id),
            UNIQUE(user_id, provider)
        );
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            provider TEXT NOT NULL CHECK(provider IN ('Google','Kakao','Naver')),
            link_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            client_key TEXT NOT NULL,
            failed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup
            ON login_attempts(email,client_key,failed_at);
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            expires_at TEXT NOT NULL,
            used_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens(user_id,expires_at);
        CREATE TABLE IF NOT EXISTS email_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','SENT','FAILED')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id TEXT NOT NULL,
            rule_type TEXT NOT NULL CHECK(rule_type IN
                ('PriceDrop','BelowTargetPrice','NewHistoricalLow','BelowAverage')),
            target_price_minor INTEGER CHECK(target_price_minor >= 0),
            platform TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
            CHECK((rule_type='BelowTargetPrice' AND target_price_minor IS NOT NULL) OR
                  (rule_type!='BelowTargetPrice' AND target_price_minor IS NULL))
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rule_id INTEGER NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
            game_id TEXT NOT NULL,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            message TEXT NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            read INTEGER NOT NULL DEFAULT 0 CHECK(read IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS notification_outbox (
            notification_id INTEGER PRIMARY KEY REFERENCES notifications(id) ON DELETE CASCADE,
            channel TEXT NOT NULL DEFAULT 'email',
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SENT','FAILED')),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            sent_at TEXT
        );
        CREATE TRIGGER IF NOT EXISTS enqueue_notification_email
        AFTER INSERT ON notifications
        WHEN COALESCE(
            (SELECT email_notifications_enabled
             FROM user_preferences
             WHERE user_id = new.user_id),
            1) = 1
        BEGIN
            INSERT INTO notification_outbox(notification_id) VALUES(new.id);
        END;

        CREATE TABLE IF NOT EXISTS favorite_games (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            PRIMARY KEY(user_id, game_id)
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            email_notifications_enabled INTEGER NOT NULL DEFAULT 1
                CHECK(email_notifications_enabled IN (0,1)),
            region TEXT NOT NULL DEFAULT 'KR' CHECK(region IN ('KR')),
            currency TEXT NOT NULL DEFAULT 'KRW' CHECK(currency IN ('KRW'))
        );

        )sql");
        if (existingVersion == 1) {
            database_.execute(R"sql(
                ALTER TABLE store_products
                    ADD COLUMN regular_price_minor INTEGER
                    CHECK (regular_price_minor >= 0);
                ALTER TABLE store_products
                    ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0
                    CHECK (discount_percent BETWEEN 0 AND 100);
                ALTER TABLE price_history
                    ADD COLUMN regular_price_minor INTEGER
                    CHECK (regular_price_minor >= 0);
                ALTER TABLE price_history
                    ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0
                    CHECK (discount_percent BETWEEN 0 AND 100);
            )sql");
        }
        if (existingVersion == 1 || existingVersion == 2) {
            database_.execute(R"sql(
                ALTER TABLE store_products
                    ADD COLUMN region TEXT NOT NULL DEFAULT 'KR'
                    CHECK (region IN ('KR'));
                ALTER TABLE store_products
                    ADD COLUMN edition TEXT NOT NULL DEFAULT 'Standard'
                    CHECK (edition IN ('Standard', 'Deluxe'));
                ALTER TABLE store_products
                    ADD COLUMN offer_type TEXT NOT NULL DEFAULT 'BaseGame'
                    CHECK (offer_type IN ('BaseGame', 'DLC', 'Bundle', 'Subscription'));
            )sql");
        }
        if (existingVersion >= 5 && existingVersion < 7) {
            // Earlier versions stored bearer tokens directly. Invalidate them
            // rather than leaving recoverable credentials in the database.
            database_.execute("DELETE FROM user_sessions;");
        }
        if (existingVersion >= 5 && existingVersion < 8) {
            database_.execute("ALTER TABLE alert_rules ADD COLUMN platform TEXT;");
        }
        if (existingVersion < 9) {
            database_.execute(R"sql(
                ALTER TABLE crawl_runs
                    ADD COLUMN products_rejected INTEGER NOT NULL DEFAULT 0
                    CHECK(products_rejected >= 0);
                ALTER TABLE crawl_runs
                    ADD COLUMN products_failed INTEGER NOT NULL DEFAULT 0
                    CHECK(products_failed >= 0);
                ALTER TABLE crawl_runs
                    ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0
                    CHECK(retry_count >= 0);
            )sql");
        }
        if (existingVersion < 10) {
            database_.execute(R"sql(
                INSERT INTO price_history_conflicts(
                    original_history_id, store, external_product_id,
                    price_minor, regular_price_minor, discount_percent,
                    currency, purchasable, observed_at, reason)
                SELECT older.id, older.store, older.external_product_id,
                       older.price_minor, older.regular_price_minor,
                       older.discount_percent, older.currency,
                       older.purchasable, older.observed_at,
                       'duplicate timestamp migrated; latest row retained'
                FROM price_history older
                WHERE EXISTS(
                    SELECT 1 FROM price_history newer
                    WHERE newer.store = older.store
                      AND newer.external_product_id = older.external_product_id
                      AND newer.observed_at = older.observed_at
                      AND newer.id > older.id);

                DELETE FROM price_history
                WHERE EXISTS(
                    SELECT 1 FROM price_history newer
                    WHERE newer.store = price_history.store
                      AND newer.external_product_id = price_history.external_product_id
                      AND newer.observed_at = price_history.observed_at
                      AND newer.id > price_history.id);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_unique_observation
                    ON price_history(store, external_product_id, observed_at);
            )sql");
        }
        if (existingVersion < 11) {
            database_.execute(R"sql(
                ALTER TABLE store_products ADD COLUMN last_checked_at TEXT;
                ALTER TABLE store_products ADD COLUMN last_successful_check_at TEXT;
                UPDATE store_products
                SET last_checked_at = COALESCE(
                        (SELECT MAX(observed_at) FROM price_history h
                         WHERE h.store = store_products.store
                           AND h.external_product_id = store_products.external_product_id),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    last_successful_check_at = COALESCE(
                        (SELECT MAX(observed_at) FROM price_history h
                         WHERE h.store = store_products.store
                           AND h.external_product_id = store_products.external_product_id),
                        strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            )sql");
        }
        database_.execute(R"sql(
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_rules_identity
            ON alert_rules(user_id,game_id,rule_type,
                COALESCE(platform,''),COALESCE(target_price_minor,-1));
        )sql");
        if (existingVersion < 12) {
            database_.execute(R"sql(
                DROP TRIGGER IF EXISTS enqueue_notification_email;
                CREATE TRIGGER enqueue_notification_email
                AFTER INSERT ON notifications
                WHEN COALESCE(
                    (SELECT email_notifications_enabled
                     FROM user_preferences
                     WHERE user_id = new.user_id),
                    1) = 1
                BEGIN
                    INSERT INTO notification_outbox(notification_id) VALUES(new.id);
                END;
            )sql");
        }
        if (usersExisted && !usersHadRole) {
            database_.execute(R"sql(
                ALTER TABLE users
                    ADD COLUMN role TEXT NOT NULL DEFAULT 'USER'
                    CHECK(role IN ('USER','ADMIN'));
            )sql");
        }
        if (existingVersion < 14 && existingVersion > 0) {
            if (!tableHasColumn(
                    database_.handle(),
                    "notification_outbox",
                    "attempt_count")) {
                database_.execute(R"sql(
                    ALTER TABLE notification_outbox
                        ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
                )sql");
            }
            if (!tableHasColumn(
                    database_.handle(),
                    "notification_outbox",
                    "last_error")) {
                database_.execute(
                    "ALTER TABLE notification_outbox ADD COLUMN last_error TEXT;");
            }
            if (!tableHasColumn(
                    database_.handle(),
                    "notification_outbox",
                    "last_attempt_at")) {
                database_.execute(
                    "ALTER TABLE notification_outbox ADD COLUMN last_attempt_at TEXT;");
            }
            if (!tableHasColumn(
                    database_.handle(),
                    "notification_outbox",
                    "next_attempt_at")) {
                database_.execute(
                    "ALTER TABLE notification_outbox ADD COLUMN next_attempt_at TEXT;");
            }
            if (!tableHasColumn(
                    database_.handle(),
                    "notification_outbox",
                    "sent_at")) {
                database_.execute(
                    "ALTER TABLE notification_outbox ADD COLUMN sent_at TEXT;");
            }
        }
        database_.execute("PRAGMA user_version = 15;");
        database_.execute("COMMIT;");
    } catch (...) {
        try {
            database_.execute("ROLLBACK;");
        } catch (...) {
        }
        throw;
    }
}

void StoreProductRepository::saveNormalizedProducts(
    const Game& game,
    const std::vector<StoreProduct>& products) const {
    database_.execute("BEGIN IMMEDIATE TRANSACTION;");
    try {
        {
            Statement statement(database_.handle(), R"sql(
                INSERT INTO games(id, title, normalized_title)
                VALUES(?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    normalized_title = excluded.normalized_title;
            )sql");
            bindText(statement.get(), 1, game.id);
            bindText(statement.get(), 2, game.title);
            bindText(statement.get(), 3, game.normalizedTitle);
            statement.execute();
        }

        for (const auto& product : products) {
            validateStoreProduct(product);
            if (product.gameId != game.id) {
                throw std::runtime_error("StoreProduct gameId does not match Game id");
            }

            {
                Statement statement(database_.handle(), R"sql(
                    SELECT game_id
                    FROM store_products
                    WHERE store = ? AND external_product_id = ?;
                )sql");
                bindText(statement.get(), 1, toString(product.store));
                bindText(statement.get(), 2, product.productId);
                if (statement.next() && columnText(statement.get(), 0) != game.id) {
                    throw std::invalid_argument(
                        "A Store product cannot be reassigned to a different Game");
                }
            }

            const auto regularPrice = regularPriceMinor(product);

            const std::string store = toString(product.store);
            const std::string currency = toString(product.currentPrice.currency);
            const std::string checkedAt = databaseUtcNow(database_.handle());
            std::string observedAt = product.observedAt
                ? *product.observedAt
                : checkedAt;
            {
                Statement statement(database_.handle(), R"sql(
                    SELECT price_minor, regular_price_minor, discount_percent,
                           currency, purchasable, observed_at
                    FROM price_history
                    WHERE store = ? AND external_product_id = ?
                    ORDER BY observed_at DESC, id DESC
                    LIMIT 1;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                if (statement.next()) {
                    const auto latestObservedAt = columnText(statement.get(), 5);
                    if (!product.observedAt && observedAt <= latestObservedAt) {
                        observedAt = nextUtcMillisecond(
                            database_.handle(), latestObservedAt);
                    }
                    if (observedAt < latestObservedAt) {
                        throw std::invalid_argument(
                            "StoreProduct observation timestamp is older than current history");
                    }
                    if (observedAt == latestObservedAt) {
                        if (observationStateMatches(
                                statement.get(), product, regularPrice, currency)) {
                            Statement checked(database_.handle(), R"sql(
                                UPDATE store_products
                                SET last_checked_at = ?, last_successful_check_at = ?
                                WHERE store = ? AND external_product_id = ?;
                            )sql");
                            bindText(checked.get(), 1, checkedAt);
                            bindText(checked.get(), 2, checkedAt);
                            bindText(checked.get(), 3, store);
                            bindText(checked.get(), 4, product.productId);
                            checked.execute();
                            continue;
                        }
                        throw std::invalid_argument(
                            "StoreProduct observation conflicts at the same timestamp");
                    }
                }
            }
            bool shouldRecordHistory = true;
            {
                Statement statement(database_.handle(), R"sql(
                    SELECT price_minor, regular_price_minor, discount_percent,
                           currency, purchasable,
                           EXISTS(
                               SELECT 1
                               FROM price_history
                               WHERE store = ? AND external_product_id = ?
                           )
                    FROM store_products
                    WHERE store = ? AND external_product_id = ?;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindText(statement.get(), 3, store);
                bindText(statement.get(), 4, product.productId);

                if (statement.next()) {
                    const bool hasHistory = sqlite3_column_int(statement.get(), 5) != 0;
                    const bool storedRegularIsNull =
                        sqlite3_column_type(statement.get(), 1) == SQLITE_NULL;
                    const bool regularPriceIsUnchanged = regularPrice
                        ? !storedRegularIsNull &&
                            sqlite3_column_int64(statement.get(), 1) == *regularPrice
                        : storedRegularIsNull;
                    const bool stateIsUnchanged =
                        sqlite3_column_int64(statement.get(), 0) ==
                            product.currentPrice.minorAmount &&
                        regularPriceIsUnchanged &&
                        sqlite3_column_int(statement.get(), 2) ==
                            product.discountPercent &&
                        columnText(statement.get(), 3) == currency &&
                        (sqlite3_column_int(statement.get(), 4) != 0) == product.purchasable;
                    shouldRecordHistory = !hasHistory || !stateIsUnchanged;
                }
            }

            {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO store_products(
                        store, external_product_id, game_id,
                        price_minor, regular_price_minor, discount_percent,
                        currency, purchasable, region, edition, offer_type,
                        last_checked_at, last_successful_check_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, external_product_id) DO UPDATE SET
                        game_id = excluded.game_id,
                        price_minor = excluded.price_minor,
                        regular_price_minor = excluded.regular_price_minor,
                        discount_percent = excluded.discount_percent,
                        currency = excluded.currency,
                        purchasable = excluded.purchasable,
                        region = excluded.region,
                        edition = excluded.edition,
                        offer_type = excluded.offer_type,
                        last_checked_at = excluded.last_checked_at,
                        last_successful_check_at = excluded.last_successful_check_at;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindText(statement.get(), 3, product.gameId);
                bindInt64(statement.get(), 4, product.currentPrice.minorAmount);
                bindOptionalInt64(statement.get(), 5, regularPrice);
                bindInt64(statement.get(), 6, product.discountPercent);
                bindText(statement.get(), 7, currency);
                bindInt64(statement.get(), 8, product.purchasable ? 1 : 0);
                bindText(statement.get(), 9, toString(product.region));
                bindText(statement.get(), 10, toString(product.edition));
                bindText(statement.get(), 11, toString(product.offerType));
                bindText(statement.get(), 12, checkedAt);
                bindText(statement.get(), 13, checkedAt);
                statement.execute();
            }

            if (shouldRecordHistory) {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO price_history(
                        store, external_product_id, price_minor,
                        regular_price_minor, discount_percent,
                        currency, purchasable, observed_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?);
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindInt64(statement.get(), 3, product.currentPrice.minorAmount);
                bindOptionalInt64(statement.get(), 4, regularPrice);
                bindInt64(statement.get(), 5, product.discountPercent);
                bindText(statement.get(), 6, currency);
                bindInt64(statement.get(), 7, product.purchasable ? 1 : 0);
                bindText(statement.get(), 8, observedAt);
                statement.execute();
            }

            {
                Statement statement(database_.handle(), R"sql(
                    DELETE FROM product_platforms
                    WHERE store = ? AND external_product_id = ?;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                statement.execute();
            }

            for (const auto platform : product.supportedPlatforms) {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO product_platforms(store, external_product_id, platform)
                    VALUES(?, ?, ?);
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindText(statement.get(), 3, toString(platform));
                statement.execute();
            }

            {
                Statement statement(database_.handle(), R"sql(
                    DELETE FROM product_compatibility
                    WHERE store = ? AND external_product_id = ?;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                statement.execute();
            }
            for (const auto& compatibility : product.compatibility) {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO product_compatibility(
                        store, external_product_id, platform, status)
                    VALUES(?, ?, ?, ?);
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindText(statement.get(), 3, toString(compatibility.platform));
                bindText(statement.get(), 4, toString(compatibility.status));
                statement.execute();
            }
        }

        database_.execute("COMMIT;");
    } catch (...) {
        try {
            database_.execute("ROLLBACK;");
        } catch (...) {
        }
        throw;
    }
}

std::vector<StoreProduct> StoreProductRepository::findProductsByGameId(
    const std::string& gameId) const {
    Statement productsStatement(database_.handle(), R"sql(
        SELECT store, external_product_id, game_id,
               price_minor, regular_price_minor, discount_percent,
               currency, purchasable, region, edition, offer_type,
               last_checked_at, last_successful_check_at,
               CASE
                   WHEN last_successful_check_at IS NULL THEN 'Unknown'
                   WHEN last_successful_check_at >=
                        strftime('%Y-%m-%dT%H:%M:%fZ','now',?2) THEN 'Fresh'
                   ELSE 'Stale'
               END
        FROM store_products
        WHERE game_id = ?1
        ORDER BY store, external_product_id;
    )sql");
    bindText(productsStatement.get(), 1, gameId);
    bindText(
        productsStatement.get(), 2,
        "-" + std::to_string(StaleAfterHours) + " hours");

    std::vector<StoreProduct> products;
    while (productsStatement.next()) {
        const std::string storeName = columnText(productsStatement.get(), 0);
        const std::string productId = columnText(productsStatement.get(), 1);

        Statement platformsStatement(database_.handle(), R"sql(
            SELECT platform
            FROM product_platforms
            WHERE store = ? AND external_product_id = ?
            ORDER BY platform;
        )sql");
        bindText(platformsStatement.get(), 1, storeName);
        bindText(platformsStatement.get(), 2, productId);

        std::vector<Platform> platforms;
        while (platformsStatement.next()) {
            platforms.push_back(parsePlatform(columnText(platformsStatement.get(), 0)));
        }

        Statement compatibilityStatement(database_.handle(), R"sql(
            SELECT platform, status
            FROM product_compatibility
            WHERE store = ? AND external_product_id = ?
            ORDER BY platform;
        )sql");
        bindText(compatibilityStatement.get(), 1, storeName);
        bindText(compatibilityStatement.get(), 2, productId);
        std::vector<PlatformCompatibility> compatibility;
        while (compatibilityStatement.next()) {
            compatibility.push_back(PlatformCompatibility{
                parsePlatform(columnText(compatibilityStatement.get(), 0)),
                parseCompatibilityStatus(columnText(compatibilityStatement.get(), 1))});
        }

        products.push_back(StoreProduct{
            productId,
            columnText(productsStatement.get(), 2),
            parseStore(storeName),
            std::move(platforms),
            Money{
                sqlite3_column_int64(productsStatement.get(), 3),
                parseCurrency(columnText(productsStatement.get(), 6))},
            sqlite3_column_int(productsStatement.get(), 7) != 0,
            std::nullopt,
            sqlite3_column_type(productsStatement.get(), 4) == SQLITE_NULL
                ? std::nullopt
                : std::optional<Money>{Money{
                    sqlite3_column_int64(productsStatement.get(), 4),
                    parseCurrency(columnText(productsStatement.get(), 6))}},
            sqlite3_column_int(productsStatement.get(), 5),
            parseRegion(columnText(productsStatement.get(), 8)),
            parseEdition(columnText(productsStatement.get(), 9)),
            parseOfferType(columnText(productsStatement.get(), 10)),
            std::move(compatibility),
            sqlite3_column_type(productsStatement.get(), 11) == SQLITE_NULL
                ? std::nullopt
                : std::optional<std::string>{columnText(productsStatement.get(), 11)},
            sqlite3_column_type(productsStatement.get(), 12) == SQLITE_NULL
                ? std::nullopt
                : std::optional<std::string>{columnText(productsStatement.get(), 12)},
            columnText(productsStatement.get(), 13) == "Fresh"
                ? PriceFreshness::Fresh
                : columnText(productsStatement.get(), 13) == "Stale"
                    ? PriceFreshness::Stale
                    : PriceFreshness::Unknown});
    }
    return products;
}

std::vector<PriceObservation> StoreProductRepository::findPriceHistory(
    Store store,
    const std::string& productId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT price_minor, regular_price_minor, discount_percent,
               currency, purchasable, observed_at
        FROM price_history
        WHERE store = ? AND external_product_id = ?
        ORDER BY observed_at, id;
    )sql");
    bindText(statement.get(), 1, toString(store));
    bindText(statement.get(), 2, productId);

    std::vector<PriceObservation> observations;
    while (statement.next()) {
        observations.push_back(PriceObservation{
            Money{
                sqlite3_column_int64(statement.get(), 0),
                parseCurrency(columnText(statement.get(), 3))},
            sqlite3_column_int(statement.get(), 4) != 0,
            columnText(statement.get(), 5),
            sqlite3_column_type(statement.get(), 1) == SQLITE_NULL
                ? std::nullopt
                : std::optional<Money>{Money{
                    sqlite3_column_int64(statement.get(), 1),
                    parseCurrency(columnText(statement.get(), 3))}},
            sqlite3_column_int(statement.get(), 2)});
    }
    return observations;
}

std::vector<PriceObservation> StoreProductRepository::findPriceHistorySince(
    Store store,
    const std::string& productId,
    const std::string& observedSince) const {
    Statement statement(database_.handle(), R"sql(
        SELECT price_minor, regular_price_minor, discount_percent,
               currency, purchasable, observed_at
        FROM price_history
        WHERE store = ? AND external_product_id = ? AND observed_at >= ?
        ORDER BY observed_at, id;
    )sql");
    bindText(statement.get(), 1, toString(store));
    bindText(statement.get(), 2, productId);
    bindText(statement.get(), 3, observedSince);

    std::vector<PriceObservation> observations;
    while (statement.next()) {
        observations.push_back(PriceObservation{
            Money{
                sqlite3_column_int64(statement.get(), 0),
                parseCurrency(columnText(statement.get(), 3))},
            sqlite3_column_int(statement.get(), 4) != 0,
            columnText(statement.get(), 5),
            sqlite3_column_type(statement.get(), 1) == SQLITE_NULL
                ? std::nullopt
                : std::optional<Money>{Money{
                    sqlite3_column_int64(statement.get(), 1),
                    parseCurrency(columnText(statement.get(), 3))}},
            sqlite3_column_int(statement.get(), 2)});
    }
    return observations;
}

void StoreProductRepository::replacePriceHistory(
    Store store,
    const std::string& productId,
    const std::vector<PriceObservation>& observations) const {
    database_.execute("BEGIN IMMEDIATE TRANSACTION;");
    try {
        {
            Statement statement(database_.handle(), R"sql(
                DELETE FROM price_history
                WHERE store = ? AND external_product_id = ?;
            )sql");
            bindText(statement.get(), 1, toString(store));
            bindText(statement.get(), 2, productId);
            statement.execute();
        }
        const PriceObservation* previousStored = nullptr;
        const PriceObservation* previousInput = nullptr;
        for (const auto& observation : observations) {
            validatePriceObservation(observation);
            if (previousInput && observation.observedAt < previousInput->observedAt) {
                throw std::invalid_argument(
                    "Price observations must be ordered by timestamp");
            }
            if (previousInput && observation.observedAt == previousInput->observedAt) {
                if (sameObservationState(*previousInput, observation)) continue;
                throw std::invalid_argument(
                    "Price observations conflict at the same timestamp");
            }
            previousInput = &observation;
            const bool unchanged = previousStored &&
                sameObservationState(*previousStored, observation);
            if (unchanged) continue;

            Statement statement(database_.handle(), R"sql(
                INSERT INTO price_history(
                    store, external_product_id, price_minor,
                    regular_price_minor, discount_percent,
                    currency, purchasable, observed_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?);
            )sql");
            bindText(statement.get(), 1, toString(store));
            bindText(statement.get(), 2, productId);
            bindInt64(statement.get(), 3, observation.price.minorAmount);
            bindOptionalInt64(
                statement.get(), 4,
                observation.regularPrice
                    ? std::optional<std::int64_t>{observation.regularPrice->minorAmount}
                    : std::nullopt);
            bindInt64(statement.get(), 5, observation.discountPercent);
            bindText(statement.get(), 6, toString(observation.price.currency));
            bindInt64(statement.get(), 7, observation.purchasable ? 1 : 0);
            bindText(statement.get(), 8, observation.observedAt);
            statement.execute();
            previousStored = &observation;
        }
        database_.execute("COMMIT;");
    } catch (...) {
        try {
            database_.execute("ROLLBACK;");
        } catch (...) {
        }
        throw;
    }
}

std::int64_t StoreProductRepository::startCrawlRun(Store store) const {
    Statement statement(database_.handle(), R"sql(
        INSERT INTO crawl_runs(store, started_at, status)
        VALUES(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'RUNNING');
    )sql");
    bindText(statement.get(), 1, toString(store));
    statement.execute();
    return sqlite3_last_insert_rowid(database_.handle());
}

void StoreProductRepository::finishCrawlRun(
    std::int64_t runId,
    CrawlRunStatus status,
    std::size_t productsFound,
    std::size_t productsRejected,
    std::size_t productsFailed,
    std::size_t retryCount,
    const std::string& errorMessage) const {
    if (status == CrawlRunStatus::Running) {
        throw std::runtime_error("A finished crawl run cannot remain RUNNING");
    }
    Statement statement(database_.handle(), R"sql(
        UPDATE crawl_runs
        SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = ?, products_found = ?, products_rejected = ?,
            products_failed = ?, retry_count = ?, error_message = ?
        WHERE id = ? AND status = 'RUNNING';
    )sql");
    bindText(statement.get(), 1, toString(status));
    bindInt64(statement.get(), 2, static_cast<std::int64_t>(productsFound));
    bindInt64(statement.get(), 3, static_cast<std::int64_t>(productsRejected));
    bindInt64(statement.get(), 4, static_cast<std::int64_t>(productsFailed));
    bindInt64(statement.get(), 5, static_cast<std::int64_t>(retryCount));
    bindText(statement.get(), 6, errorMessage);
    bindInt64(statement.get(), 7, runId);
    statement.execute();
    if (sqlite3_changes(database_.handle()) != 1) {
        throw std::runtime_error("Crawl run was not found or already finished");
    }
}

void StoreProductRepository::recordCollectionRejection(
    std::int64_t runId,
    Store store,
    const std::string& gameId,
    const std::string& productId,
    const std::string& reason) const {
    Statement statement(database_.handle(), R"sql(
        INSERT INTO collection_rejections(
            crawl_run_id, store, game_id, external_product_id, reason)
        VALUES(?, ?, ?, ?, ?);
    )sql");
    bindInt64(statement.get(), 1, runId);
    bindText(statement.get(), 2, toString(store));
    bindText(statement.get(), 3, gameId);
    bindText(statement.get(), 4, productId);
    bindText(statement.get(), 5, reason);
    statement.execute();
}

void StoreProductRepository::recordProductCheckFailure(
    Store store,
    const std::string& productId) const {
    Statement statement(database_.handle(), R"sql(
        UPDATE store_products
        SET last_checked_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
        WHERE store = ? AND external_product_id = ?;
    )sql");
    bindText(statement.get(), 1, toString(store));
    bindText(statement.get(), 2, productId);
    statement.execute();
}

std::vector<CrawlRunRecord> StoreProductRepository::findCrawlRuns() const {
    Statement statement(database_.handle(), R"sql(
        SELECT id, store, status, products_found, products_rejected,
               products_failed, retry_count, started_at,
               COALESCE(finished_at, ''), error_message
        FROM crawl_runs
        ORDER BY id;
    )sql");

    std::vector<CrawlRunRecord> runs;
    while (statement.next()) {
        runs.push_back(CrawlRunRecord{
            sqlite3_column_int64(statement.get(), 0),
            parseStore(columnText(statement.get(), 1)),
            parseCrawlRunStatus(columnText(statement.get(), 2)),
            static_cast<std::size_t>(sqlite3_column_int64(statement.get(), 3)),
            static_cast<std::size_t>(sqlite3_column_int64(statement.get(), 4)),
            static_cast<std::size_t>(sqlite3_column_int64(statement.get(), 5)),
            static_cast<std::size_t>(sqlite3_column_int64(statement.get(), 6)),
            columnText(statement.get(), 7),
            columnText(statement.get(), 8),
            columnText(statement.get(), 9)});
    }
    return runs;
}

std::vector<CollectionRejection>
StoreProductRepository::findCollectionRejections(std::int64_t runId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT id, crawl_run_id, store, game_id, external_product_id,
               reason, rejected_at
        FROM collection_rejections
        WHERE crawl_run_id = ?
        ORDER BY id;
    )sql");
    bindInt64(statement.get(), 1, runId);
    std::vector<CollectionRejection> rejections;
    while (statement.next()) {
        rejections.push_back(CollectionRejection{
            sqlite3_column_int64(statement.get(), 0),
            sqlite3_column_int64(statement.get(), 1),
            parseStore(columnText(statement.get(), 2)),
            columnText(statement.get(), 3),
            columnText(statement.get(), 4),
            columnText(statement.get(), 5),
            columnText(statement.get(), 6)});
    }
    return rejections;
}

}  // namespace game_price
