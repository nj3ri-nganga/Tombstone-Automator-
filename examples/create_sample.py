"""Create the five-company live-test INPUT. Generates no logos or placeholders."""
from pathlib import Path
from openpyxl import Workbook


def main():
    destination = Path(__file__).resolve().parent / 'five_companies.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Transactions'
    sheet.append(['Company', 'Website'])
    for name, domain in [('Microsoft', 'microsoft.com'), ('Apple', 'apple.com'),
                         ('NVIDIA', 'nvidia.com'), ('Salesforce', 'salesforce.com'),
                         ('Adobe', 'adobe.com')]:
        sheet.append([name, 'https://www.' + domain])
    workbook.save(destination)
    workbook.close()
    print(destination)


if __name__ == '__main__':
    main()
