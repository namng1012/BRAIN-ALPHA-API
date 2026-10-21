from Functions.data import BrainData
from Functions.login import BrainLogin


def main():
    login = BrainLogin()
    s = login.get_session()
    if s is None:
        return
    print("Login successful. JWT:")
    print(login.get_token(s))

    data = BrainData(s, login.base_url)
    scope = {"instrumentType": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
    datasets = data.datasets(scope)
    datafields = data.datafields(scope)

    print(f"\nDatasets: {len(datasets)}  Data fields: {len(datafields)}")
    print("\nDataset columns:")
    print(list(datasets.columns))
    print("\nData field columns:")
    print(list(datafields.columns))
    print("\nData field types:")
    print(datafields["type"].value_counts())
    print("\nDataset categories:")
    print(datasets["categoryname"].value_counts())
    print("\nData field categories:")
    print(datafields["categoryname"].value_counts())


if __name__ == "__main__":
    main()
