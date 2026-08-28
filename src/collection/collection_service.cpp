#include "game_price/collection/collection_service.h"
#include "game_price/collection/collection_error.h"
#include "game_price/notification/alert_service.h"

#include <exception>
#include <chrono>
#include <algorithm>
#include <set>
#include <stdexcept>
#include <utility>
#include <thread>

namespace game_price {
namespace {

void validateCatalogIdentity(
    const GameCatalog& catalog,
    const Game& game,
    const StoreProductProvider& provider,
    const StoreProduct& product) {
    if (product.store != provider.store()) {
        throw std::invalid_argument(
            "Provider returned a product for a different Store");
    }
    const auto catalogProduct = catalog.findStoreProduct(
        product.store, product.productId);
    if (!catalogProduct || catalogProduct->gameId != game.id) {
        throw std::invalid_argument(
            "Provider returned a Store product without an exact Catalog mapping: " +
            product.productId);
    }
    if (product.gameId != catalogProduct->gameId ||
        product.region != catalogProduct->region ||
        product.edition != catalogProduct->edition ||
        product.offerType != catalogProduct->offerType) {
        throw std::invalid_argument(
            "Provider product identity does not match the Catalog: " +
            product.productId);
    }
}

std::chrono::milliseconds retryDelay(
    std::chrono::milliseconds initial,
    std::size_t failedAttempt) {
    constexpr auto maximum = std::chrono::milliseconds{30'000};
    auto delay = initial;
    for (std::size_t index = 1; index < failedAttempt && delay < maximum; ++index) {
        delay = std::min(delay * 2, maximum);
    }
    return delay;
}

}  // namespace

CollectionService::CollectionService(
    const GameCatalog& catalog,
    StoreProductRepository& repository,
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers,
    std::size_t maxAttemptsPerStore,
    const AlertService* alertService,
    std::chrono::milliseconds initialRetryDelay,
    std::function<void(std::chrono::milliseconds)> sleeper)
    : catalog_(catalog), repository_(repository),
      providers_(std::move(providers)),
      maxAttemptsPerStore_(maxAttemptsPerStore), alertService_(alertService),
      initialRetryDelay_(initialRetryDelay), sleeper_(std::move(sleeper)) {
    if (maxAttemptsPerStore_ == 0) {
        throw std::invalid_argument("maxAttemptsPerStore must be at least 1");
    }
    if (initialRetryDelay_.count() < 0) {
        throw std::invalid_argument("initialRetryDelay cannot be negative");
    }
    if (!sleeper_) {
        sleeper_ = [](std::chrono::milliseconds delay) {
            std::this_thread::sleep_for(delay);
        };
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
                std::set<std::string> productIds;
                std::size_t accepted = 0;
                std::size_t rejected = 0;
                for (const auto& product : products) {
                    try {
                        if (!productIds.insert(product.productId).second) {
                            throw std::invalid_argument(
                                "Provider returned a duplicate Store product: " +
                                product.productId);
                        }
                        validateCatalogIdentity(catalog_, game, provider, product);
                        repository_.saveNormalizedProducts(game, {product});
                        ++accepted;
                    } catch (const std::invalid_argument& error) {
                        repository_.recordProductCheckFailure(
                            provider.store(), product.productId);
                        repository_.recordCollectionRejection(
                            runId, provider.store(), game.id,
                            product.productId, error.what());
                        ++rejected;
                    }
                }
                if (alertService_ && accepted > 0) alertService_->evaluateGame(game.id);
                const bool allRejected = !products.empty() && accepted == 0;
                const auto status = allRejected
                    ? CrawlRunStatus::Failed
                    : CrawlRunStatus::Succeeded;
                const std::string message = allRejected
                    ? "All normalized products were rejected"
                    : rejected > 0
                        ? std::to_string(rejected) + " normalized product(s) rejected"
                        : "";
                repository_.finishCrawlRun(
                    runId, status, accepted, rejected, 0, attempt - 1, message);
                result.runs.push_back(CollectionRunResult{
                    provider.store(), status, attempt, accepted, rejected, 0,
                    attempt - 1, message});
                result.totalProducts += accepted;
                break;
            } catch (const PermanentCollectionError& error) {
                for (const auto& catalogProduct :
                     catalog_.storeProducts(provider.store())) {
                    if (catalogProduct.gameId == game.id) {
                        repository_.recordProductCheckFailure(
                            provider.store(), catalogProduct.productId);
                    }
                }
                repository_.finishCrawlRun(
                    runId, CrawlRunStatus::Failed, 0, 0, 1,
                    attempt - 1, error.what());
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Failed, attempt, 0, 0, 1,
                    attempt - 1, error.what()});
                break;
            } catch (const std::exception& error) {
                for (const auto& catalogProduct :
                     catalog_.storeProducts(provider.store())) {
                    if (catalogProduct.gameId == game.id) {
                        repository_.recordProductCheckFailure(
                            provider.store(), catalogProduct.productId);
                    }
                }
                repository_.finishCrawlRun(
                    runId, CrawlRunStatus::Failed, 0, 0, 1,
                    attempt - 1, error.what());
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Failed, attempt, 0, 0, 1,
                    attempt - 1, error.what()});
                if (attempt < maxAttemptsPerStore_) {
                    sleeper_(retryDelay(initialRetryDelay_, attempt));
                }
            } catch (...) {
                const std::string message = "Unknown collection error";
                for (const auto& catalogProduct :
                     catalog_.storeProducts(provider.store())) {
                    if (catalogProduct.gameId == game.id) {
                        repository_.recordProductCheckFailure(
                            provider.store(), catalogProduct.productId);
                    }
                }
                repository_.finishCrawlRun(
                    runId, CrawlRunStatus::Failed, 0, 0, 1,
                    attempt - 1, message);
                result.runs.push_back(CollectionRunResult{
                    provider.store(), CrawlRunStatus::Failed, attempt, 0, 0, 1,
                    attempt - 1, message});
                if (attempt < maxAttemptsPerStore_) {
                    sleeper_(retryDelay(initialRetryDelay_, attempt));
                }
            }
        }
    }
    return result;
}

}  // namespace game_price
