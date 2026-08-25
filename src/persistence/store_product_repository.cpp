#include "game_price/persistence/store_product_repository.h"

#include "game_price/domain/domain_types.h"

#include <sqlite3.h>

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

std::string columnText(sqlite3_stmt* statement, int index) {
    const auto* text = sqlite3_column_text(statement, index);
    if (!text) {
        throw std::runtime_error("Unexpected NULL text column");
    }
    return reinterpret_cast<const char*>(text);
}

Store parseStore(const std::string& value) {
    if (value == "Steam") return Store::Steam;
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
    throw std::runtime_error("Unknown Platform value in database: " + value);
}

Currency parseCurrency(const std::string& value) {
    if (value == "KRW") return Currency::KRW;
    throw std::runtime_error("Unknown Currency value in database: " + value);
}

CrawlRunStatus parseCrawlRunStatus(const std::string& value) {
    if (value == "RUNNING") return CrawlRunStatus::Running;
    if (value == "SUCCEEDED") return CrawlRunStatus::Succeeded;
    if (value == "FAILED") return CrawlRunStatus::Failed;
    throw std::runtime_error("Unknown crawl run status in database: " + value);
}

}  // namespace

StoreProductRepository::StoreProductRepository(Database& database) : database_(database) {}

void StoreProductRepository::initializeSchema() const {
    const int existingVersion = database_.userVersion();
    if (existingVersion > CurrentSchemaVersion) {
        throw std::runtime_error(
            "Database schema version " + std::to_string(existingVersion) +
            " is newer than supported version " +
            std::to_string(CurrentSchemaVersion));
    }
    if (existingVersion == CurrentSchemaVersion) return;

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
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL CHECK (purchasable IN (0, 1)),
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

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            external_product_id TEXT NOT NULL,
            price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
            currency TEXT NOT NULL,
            purchasable INTEGER NOT NULL CHECK (purchasable IN (0, 1)),
            observed_at TEXT NOT NULL,
            FOREIGN KEY (store, external_product_id)
                REFERENCES store_products(store, external_product_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_product_time
            ON price_history(store, external_product_id, observed_at);

        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
            products_found INTEGER NOT NULL DEFAULT 0 CHECK (products_found >= 0),
            error_message TEXT NOT NULL DEFAULT ''
        );

        )sql");
        database_.execute("PRAGMA user_version = 1;");
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
            if (product.gameId != game.id) {
                throw std::runtime_error("StoreProduct gameId does not match Game id");
            }

            const std::string store = toString(product.store);
            const std::string currency = toString(product.currentPrice.currency);
            bool shouldRecordHistory = true;
            {
                Statement statement(database_.handle(), R"sql(
                    SELECT price_minor, currency, purchasable,
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
                    const bool hasHistory = sqlite3_column_int(statement.get(), 3) != 0;
                    const bool stateIsUnchanged =
                        sqlite3_column_int64(statement.get(), 0) ==
                            product.currentPrice.minorAmount &&
                        columnText(statement.get(), 1) == currency &&
                        (sqlite3_column_int(statement.get(), 2) != 0) == product.purchasable;
                    shouldRecordHistory = !hasHistory || !stateIsUnchanged;
                }
            }

            {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO store_products(
                        store, external_product_id, game_id,
                        price_minor, currency, purchasable)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(store, external_product_id) DO UPDATE SET
                        game_id = excluded.game_id,
                        price_minor = excluded.price_minor,
                        currency = excluded.currency,
                        purchasable = excluded.purchasable;
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindText(statement.get(), 3, product.gameId);
                bindInt64(statement.get(), 4, product.currentPrice.minorAmount);
                bindText(statement.get(), 5, currency);
                bindInt64(statement.get(), 6, product.purchasable ? 1 : 0);
                statement.execute();
            }

            if (shouldRecordHistory) {
                Statement statement(database_.handle(), R"sql(
                    INSERT INTO price_history(
                        store, external_product_id, price_minor,
                        currency, purchasable, observed_at)
                    VALUES(?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                )sql");
                bindText(statement.get(), 1, store);
                bindText(statement.get(), 2, product.productId);
                bindInt64(statement.get(), 3, product.currentPrice.minorAmount);
                bindText(statement.get(), 4, currency);
                bindInt64(statement.get(), 5, product.purchasable ? 1 : 0);
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
               price_minor, currency, purchasable
        FROM store_products
        WHERE game_id = ?
        ORDER BY store, external_product_id;
    )sql");
    bindText(productsStatement.get(), 1, gameId);

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

        products.push_back(StoreProduct{
            productId,
            columnText(productsStatement.get(), 2),
            parseStore(storeName),
            std::move(platforms),
            Money{
                sqlite3_column_int64(productsStatement.get(), 3),
                parseCurrency(columnText(productsStatement.get(), 4))},
            sqlite3_column_int(productsStatement.get(), 5) != 0});
    }
    return products;
}

std::vector<PriceObservation> StoreProductRepository::findPriceHistory(
    Store store,
    const std::string& productId) const {
    Statement statement(database_.handle(), R"sql(
        SELECT price_minor, currency, purchasable, observed_at
        FROM price_history
        WHERE store = ? AND external_product_id = ?
        ORDER BY id;
    )sql");
    bindText(statement.get(), 1, toString(store));
    bindText(statement.get(), 2, productId);

    std::vector<PriceObservation> observations;
    while (statement.next()) {
        observations.push_back(PriceObservation{
            Money{
                sqlite3_column_int64(statement.get(), 0),
                parseCurrency(columnText(statement.get(), 1))},
            sqlite3_column_int(statement.get(), 2) != 0,
            columnText(statement.get(), 3)});
    }
    return observations;
}

std::vector<PriceObservation> StoreProductRepository::findPriceHistorySince(
    Store store,
    const std::string& productId,
    const std::string& observedSince) const {
    Statement statement(database_.handle(), R"sql(
        SELECT price_minor, currency, purchasable, observed_at
        FROM price_history
        WHERE store = ? AND external_product_id = ? AND observed_at >= ?
        ORDER BY id;
    )sql");
    bindText(statement.get(), 1, toString(store));
    bindText(statement.get(), 2, productId);
    bindText(statement.get(), 3, observedSince);

    std::vector<PriceObservation> observations;
    while (statement.next()) {
        observations.push_back(PriceObservation{
            Money{
                sqlite3_column_int64(statement.get(), 0),
                parseCurrency(columnText(statement.get(), 1))},
            sqlite3_column_int(statement.get(), 2) != 0,
            columnText(statement.get(), 3)});
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
        for (const auto& observation : observations) {
            Statement statement(database_.handle(), R"sql(
                INSERT INTO price_history(
                    store, external_product_id, price_minor,
                    currency, purchasable, observed_at)
                VALUES(?, ?, ?, ?, ?, ?);
            )sql");
            bindText(statement.get(), 1, toString(store));
            bindText(statement.get(), 2, productId);
            bindInt64(statement.get(), 3, observation.price.minorAmount);
            bindText(statement.get(), 4, toString(observation.price.currency));
            bindInt64(statement.get(), 5, observation.purchasable ? 1 : 0);
            bindText(statement.get(), 6, observation.observedAt);
            statement.execute();
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
    const std::string& errorMessage) const {
    if (status == CrawlRunStatus::Running) {
        throw std::runtime_error("A finished crawl run cannot remain RUNNING");
    }
    Statement statement(database_.handle(), R"sql(
        UPDATE crawl_runs
        SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = ?, products_found = ?, error_message = ?
        WHERE id = ? AND status = 'RUNNING';
    )sql");
    bindText(statement.get(), 1, toString(status));
    bindInt64(statement.get(), 2, static_cast<std::int64_t>(productsFound));
    bindText(statement.get(), 3, errorMessage);
    bindInt64(statement.get(), 4, runId);
    statement.execute();
    if (sqlite3_changes(database_.handle()) != 1) {
        throw std::runtime_error("Crawl run was not found or already finished");
    }
}

std::vector<CrawlRunRecord> StoreProductRepository::findCrawlRuns() const {
    Statement statement(database_.handle(), R"sql(
        SELECT id, store, status, products_found, started_at,
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
            columnText(statement.get(), 4),
            columnText(statement.get(), 5),
            columnText(statement.get(), 6)});
    }
    return runs;
}

}  // namespace game_price
