#pragma once

#include "game_price/notification/account_repository.h"

#include <optional>
#include <string>

namespace game_price {

struct AuthResult { UserAccount user; std::string token; };

class AuthService {
public:
    explicit AuthService(AccountRepository& repository);
    AuthResult registerUser(const std::string& email, const std::string& password) const;
    std::optional<AuthResult> login(const std::string& email, const std::string& password) const;
    std::optional<UserAccount> authenticate(const std::string& token) const;
    void logout(const std::string& token) const;
private:
    AccountRepository& repository_;
};

}  // namespace game_price
