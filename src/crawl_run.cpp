#include "game_price/crawl_run.h"

namespace game_price {

std::string toString(CrawlRunStatus status) {
    switch (status) {
        case CrawlRunStatus::Running: return "RUNNING";
        case CrawlRunStatus::Succeeded: return "SUCCEEDED";
        case CrawlRunStatus::Failed: return "FAILED";
    }
    return "UNKNOWN";
}

}  // namespace game_price
