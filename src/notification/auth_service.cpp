#include "game_price/notification/auth_service.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace game_price {
namespace {
constexpr int Iterations = 210000;
std::string hex(const unsigned char* data, std::size_t size) {
    std::ostringstream out;
    for (std::size_t i=0;i<size;++i) out << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
    return out.str();
}
std::vector<unsigned char> unhex(const std::string& value) {
    if (value.size()%2) throw std::runtime_error("invalid password hash");
    std::vector<unsigned char> result(value.size()/2);
    for (std::size_t i=0;i<result.size();++i) result[i]=static_cast<unsigned char>(std::stoul(value.substr(i*2,2),nullptr,16));
    return result;
}
std::string normalizeEmail(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c){return static_cast<char>(std::tolower(c));});
    if (value.size() < 3 || value.size() > 254 || value.find('@') == std::string::npos)
        throw std::invalid_argument("valid email is required");
    return value;
}
std::string hashPassword(const std::string& password) {
    if (password.size() < 8 || password.size() > 128)
        throw std::invalid_argument("password must contain 8 to 128 characters");
    std::array<unsigned char,16> salt{}; std::array<unsigned char,32> hash{};
    if (RAND_bytes(salt.data(), salt.size()) != 1 ||
        PKCS5_PBKDF2_HMAC(password.c_str(), password.size(), salt.data(), salt.size(),
            Iterations, EVP_sha256(), hash.size(), hash.data()) != 1)
        throw std::runtime_error("password hashing failed");
    return std::to_string(Iterations)+"$"+hex(salt.data(),salt.size())+"$"+hex(hash.data(),hash.size());
}
bool verifyPassword(const std::string& password, const std::string& encoded) {
    const auto first=encoded.find('$'), second=encoded.find('$',first+1);
    if (first==std::string::npos || second==std::string::npos) return false;
    try {
        const int iterations=std::stoi(encoded.substr(0,first));
        const auto salt=unhex(encoded.substr(first+1,second-first-1));
        const auto expected=unhex(encoded.substr(second+1));
        std::vector<unsigned char> actual(expected.size());
        if (PKCS5_PBKDF2_HMAC(password.c_str(), password.size(), salt.data(), salt.size(),
                iterations, EVP_sha256(), actual.size(), actual.data()) != 1) return false;
        return expected.size()==actual.size() && CRYPTO_memcmp(expected.data(),actual.data(),actual.size())==0;
    } catch (...) { return false; }
}
}
AuthService::AuthService(AccountRepository& repository):repository_(repository){}
AuthResult AuthService::registerUser(const std::string& email,const std::string& password) const {
    const auto normalized=normalizeEmail(email);
    if (repository_.findUserByEmail(normalized)) throw std::invalid_argument("email is already registered");
    const auto user=repository_.createUser(normalized,hashPassword(password));
    return AuthResult{user,repository_.createSession(user.id)};
}
std::optional<AuthResult> AuthService::login(const std::string& email,const std::string& password) const {
    const auto found=repository_.findUserByEmail(normalizeEmail(email));
    if (!found || !verifyPassword(password,found->second)) return std::nullopt;
    return AuthResult{found->first,repository_.createSession(found->first.id)};
}
std::optional<UserAccount> AuthService::authenticate(const std::string& token) const { return repository_.findUserBySession(token); }
void AuthService::logout(const std::string& token) const { repository_.deleteSession(token); }
}  // namespace game_price
