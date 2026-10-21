from Functions.login import BrainLogin


def main():
    login = BrainLogin()
    s = login.get_session()
    if s is None:
        return
    print("Login successful. JWT:")
    print(login.get_token(s))


if __name__ == "__main__":
    main()
