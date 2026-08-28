#include "game_price/collection/collection_service.h"
#include "game_price/notification/alert_service.h"

#include <exception>
#include <stdexcept>
#include <utility>

namespace game_price {

CollectionService::CollectionService(
    StoreProductRepository& repository,
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers,
    std::size_t maxAttemptsPerStore,
    const AlertService* alertService)
    : repository_(repository),
      providers_(std::move(providers)),
      maxAttemptsPerStore_(maxAttemptsPerStore), alertService_(alertService) {
    if (maxAttemptsPerStore_ == 0) {
        throw std::invalid_argument("maxAttemptsPerStore must be at least 1");
    }
}

CollectionResult CollectionService::collect(const Game& game) const {
    CollectionResult result;
    for (const auto& providerReference : providers_) {
        const auto& provider = providerReference.get();
        for (std::size_t attempt = 1; attempt <= maxAttemptsPerStore_; ++attempt) {
            const auto runId = repository_.startCrawlRun(provider.store());
            try {
                const auto products = provider.findProducts(game.id);
                for (const auto& product : products) {
                    if (product.store != provider.store()) {
                        throw std::runtime_error(
                            "Provider returned a product for a different Store");
                    }
                }
                repository_.saveNormalizedProducts(game, products);
                if (alertService_) alertService_->evaluateGame(game.id);
                repository_.finishCrawlRun(
                    runId, CrawlRunStatus::Succeeded, products.size(), "");
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Succeeded,
                    attempt, products.size(), ""});
                result.totalProducts += products.size();
                break;
            } catch (const std::exception& error) {
                repository_.finishCrawlRun(runId, CrawlRunStatus::Failed, 0, error.what());
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Failed, attempt, 0, error.what()});
            } catch (...) {
                const std::string message = "Unknown collection error";
                repository_.finishCrawlRun(runId, CrawlRunStatus::Failed, 0, message);
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Failed, attempt, 0, message});
            }
        }
    }
    return result;
}

}  // namespace game_price
