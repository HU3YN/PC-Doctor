/*
 * A very small test runner, so the host tests need nothing but a compiler.
 * TEST(name) registers a function; CHECK / CHECK_EQ record a failure and keep
 * going, so one run reports every problem.
 */
#ifndef PCD_MINI_TEST_H
#define PCD_MINI_TEST_H

#include <cstdio>
#include <vector>

namespace mini_test {

struct Case {
    const char *name;
    void (*fn)();
};

inline std::vector<Case> &cases()
{
    static std::vector<Case> all;
    return all;
}

inline int &failures()
{
    static int count = 0;
    return count;
}

inline int &checks()
{
    static int count = 0;
    return count;
}

struct Registrar {
    Registrar(const char *name, void (*fn)())
    {
        Case c = {name, fn};
        cases().push_back(c);
    }
};

inline int run_all()
{
    int failed_cases = 0;
    for (size_t i = 0; i < cases().size(); i++) {
        int before = failures();
        cases()[i].fn();
        bool ok = (failures() == before);
        std::printf("%s  %s\n", ok ? "ok  " : "FAIL", cases()[i].name);
        if (!ok) {
            failed_cases++;
        }
    }
    std::printf("\n%d tests, %d passed, %d failed (%d checks)\n", (int)cases().size(),
                (int)cases().size() - failed_cases, failed_cases, checks());
    return failed_cases == 0 ? 0 : 1;
}

} // namespace mini_test

#define TEST(name)                                                       \
    static void name();                                                  \
    static mini_test::Registrar registrar_##name(#name, name);           \
    static void name()

#define CHECK(cond)                                                      \
    do {                                                                 \
        mini_test::checks()++;                                           \
        if (!(cond)) {                                                   \
            mini_test::failures()++;                                     \
            std::printf("    %s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
        }                                                                \
    } while (0)

#define CHECK_EQ(actual, expected)                                       \
    do {                                                                 \
        long long a_ = (long long)(actual);                              \
        long long e_ = (long long)(expected);                            \
        mini_test::checks()++;                                           \
        if (a_ != e_) {                                                  \
            mini_test::failures()++;                                     \
            std::printf("    %s:%d: %s is %lld (0x%llX), expected %lld (0x%llX)\n", __FILE__, \
                        __LINE__, #actual, a_, (unsigned long long)a_, e_,          \
                        (unsigned long long)e_);                         \
        }                                                                \
    } while (0)

#endif /* PCD_MINI_TEST_H */
