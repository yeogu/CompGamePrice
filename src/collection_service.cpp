#include "game_price/collection_service.h"

#include <exception>
#include <utility>

namespace game_price {

CollectionService::CollectionService(
    StoreProductRepository& repository,
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers)
    : repository_(repository), providers_(std::move(providers)) {}

CollectionResult CollectionService::collect(const Game& game) const {
    CollectionResult result;
    for (const auto& providerReference : providers_) {
        const auto& provider = providerReference.get();
        const auto runId = repository_.startCrawlRun(provider.store());
        try {
            const auto products = provider.findProducts(game.id);
            repository_.saveNormalizedProducts(game, products);
            repository_.finishCrawlRun(
                runId, CrawlRunStatus::Succeeded, products.size(), "");
            result.runs.push_back(CollectionRunResult{
                provider.store(), CrawlRunStatus::Succeeded, products.size(), ""});
            result.totalProducts += products.size();
        } catch (const std::exception& error) {
            repository_.finishCrawlRun(runId, CrawlRunStatus::Failed, 0, error.what());
            result.runs.push_back(CollectionRunResult{
                provider.store(), CrawlRunStatus::Failed, 0, error.what()});
        } catch (...) {
            const std::string message = "Unknown collection error";
            repository_.finishCrawlRun(runId, CrawlRunStatus::Failed, 0, message);
            result.runs.push_back(CollectionRunResult{
                provider.store(), CrawlRunStatus::Failed, 0, message});
        }
    }
    return result;
}

}  // namespace game_price
