#pragma once

#include "game_price/domain_types.h"

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
    std::string startedAt;
    std::string finishedAt;
    std::string errorMessage;
};

struct CollectionRunResult {
    Store store;
    CrawlRunStatus status{CrawlRunStatus::Running};
    std::size_t productsFound{};
    std::string errorMessage;
};

struct CollectionResult {
    std::vector<CollectionRunResult> runs;
    std::size_t totalProducts{};
};

std::string toString(CrawlRunStatus status);

}  // namespace game_price
