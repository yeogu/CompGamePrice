#pragma once

#include "game_price/domain/domain_types.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace game_price {

enum class CrawlRunStatus {
    Running,
    Succeeded,
    Failed
};

struct CrawlRunRecord {
    std::int64_t id{};
    Store store;
    CrawlRunStatus status{CrawlRunStatus::Running};
    std::size_t productsFound{};
    std::size_t productsRejected{};
    std::size_t productsFailed{};
    std::size_t retryCount{};
    std::string startedAt;
    std::string finishedAt;
    std::string errorMessage;
};

struct CollectionRunResult {
    Store store;
    CrawlRunStatus status{CrawlRunStatus::Running};
    std::size_t attemptNumber{};
    std::size_t productsFound{};
    std::size_t productsRejected{};
    std::size_t productsFailed{};
    std::size_t retryCount{};
    std::string errorMessage;
};

struct CollectionRejection {
    std::int64_t id{};
    std::int64_t crawlRunId{};
    Store store;
    std::string gameId;
    std::string productId;
    std::string reason;
    std::string rejectedAt;
};

struct CollectionResult {
    std::vector<CollectionRunResult> runs;
    std::size_t totalProducts{};
};

std::string toString(CrawlRunStatus status);

}  // namespace game_price
