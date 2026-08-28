#pragma once

#include <stdexcept>
#include <string>

namespace game_price {

class TransientCollectionError : public std::runtime_error {
public:
    explicit TransientCollectionError(const std::string& message)
        : std::runtime_error(message) {}
};

class PermanentCollectionError : public std::runtime_error {
public:
    explicit PermanentCollectionError(const std::string& message)
        : std::runtime_error(message) {}
};

}  // namespace game_price
