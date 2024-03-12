import json
import sys
from decimal import Decimal
import logging
import re

import requests

"""
Decorators

"""


def try_or_none(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(str(e))
            return None

    return wrapper


class EstateObject(object):
    def __init__(self):
        # Название жилого комплекса + регион
        self.complex: str = None
        # Код типа объекта
        self.type: str = None
        # Очередь
        self.phase: str = None
        # Корпус
        self.building: str = None
        # Номер секции (подъезда)
        self.section: str = None
        # Стоимость объекта без отделки и без скидки
        self.price_base: Decimal = None
        # Стоимость объекта с отделкой без скидки
        self.price_finished: Decimal = None
        # Стоимость объекта без отделки и со скидкой
        self.price_sale: Decimal = None
        # Стоимость объекта с отделкой и со скидкой
        self.price_finished_sale: Decimal = None
        # Площадь
        self.area: Decimal = None
        # Жилая Площадь
        self.living_area: Decimal = None
        # Номер объекта
        self.number: str = None
        # number_on_site
        self.number_on_site: str = None
        # rooms
        # Для квартир-студий или апартаментов-студий возвращается 'studio',
        # иначе число комнат (int).
        self.rooms = None
        # Этаж
        self.floor: int = None
        # Доступен ли объект для продажи
        self.in_sale: int = None
        # Статус
        self.sale_status: str = None
        # Признак что объект с отделкой | int/optional
        self.finished: int = None
        # Название валюты
        # Устанавливать только если валюта отлична от рублей
        self.currency: str = None
        # Высота потолка
        # Если не указана или указана отдельно на сайте - None.
        self.ceil: Decimal = None
        # Артикул
        self.article: str = None
        # Тип отделки
        self.finishing_name: str = None
        # Меблировка
        # 1 или 0 только если указана у объекта.
        # Если указана отдельно на сайте, или неизвестно - None.
        self.furniture: int = None
        # Стоимость меблировки, если она указана.
        self.furniture_price: float = None
        # Планировка
        self.plan: str = None
        # Особенности, характеристики
        # Как указано на сайте, например: «распашная», «окна на две стороны»,
        # «гардеробная комната», «ванная с окном», «с балконом», «видовая»,
        # «с камином», «3 с/у», «раздельный с/у», «угловая», «с террасой».
        self.feature: list[str] = None
        # Вид из окна
        self.view: list[str] = None
        # Европланировка
        self.euro_planning: int = None
        # Скидки, акции и подарки
        self.sale: list[str] = None
        # Размер скидки в процентах (float/int)
        self.discount_percent: float = None
        # Размер скидки в валюте
        self.discount: float = None
        # Комментарий
        self.comment: str = None
        # Ссылка на страницу квартиры (Абсолютный URL)
        self.flat_url: str = None
        # Срок ввода для корпуса, формат “IV кв 2023”
        # Подробнее см. инструкцию
        self.comissioning: str = None
        # Переуступка. Можно ставить только 1, там где это понятно
        self.cession: int = None


class BaseParser(object):
    def __init__(self, host, comissions):
        self.host = host
        self.comissions = comissions

    def get_building(self, value):
        is_phase = re.search(r"\d+ этап", value, flags=re.IGNORECASE)
        if not is_phase:
            return re.sub(r"дом", "", value, flags=re.IGNORECASE).strip()

    def get_phase(self, value):
        is_phase = re.search(r"\d+ этап", value, flags=re.IGNORECASE)
        if is_phase:
            return re.search(r"\d+", value).group()

    def get_rooms(self, rooms, is_studio):
        if is_studio:
            return "studio"
        return rooms

    def get_price(self, price_node):
        return Decimal(price_node["value"])

    def get_section(self, value):
        return value.lower().replace("подъезд", "").strip()

    def get_plan(self, value):
        if value and len(value):
            return value[0]["source"]
        return None

    def get_view(self, data):
        view_block = filter(lambda e: e["id"] == "window", data["custom_fields"])
        view_block = tuple(view_block)
        if len(view_block):
            views = view_block[0]["value"]
            return [views] if views else None
        return None

    def _custom_field_by_id(self, custom_fields, field_id):
        field = tuple(filter(lambda e: e["id"] == field_id, custom_fields))
        return field[0] if len(field) else None

    def get_article(self, custom_fields):
        article = self._custom_field_by_id(custom_fields, "code")
        return article["value"] if article else None

    def get_finishing_name(self, custom_fields):
        facing = self._custom_field_by_id(custom_fields, "facing")
        if not facing:
            return None
        value = facing.get("value", "")
        if not value:
            return None
        not_finished = re.search(r"без |нет", value, flags=re.IGNORECASE)
        if not not_finished:
            return value
        return None

    def get_finished(self, custom_fields):
        facing = self._custom_field_by_id(custom_fields, "facing")
        if facing and facing["value"]:
            value = facing.get("value", "")
            not_finished = re.search(r"без |нет", value, flags=re.IGNORECASE)
            return int(not bool(not_finished))
        return None

    def get_offer(self, data):
        price = data["price"]["value"]
        price_sale = None
        discount_percent = None
        discount_sum = None
        if len(data["specialOffers"]):
            offer = data["specialOffers"][0]
            discount = offer["discount"]
            price_sale = discount["calculate"]["price"]
            units = discount["unit"]

            dicount_value = discount["value"]
            if dicount_value:
                if units.lower() == "percent":
                    discount_percent = float(dicount_value)
                else:
                    discount_sum = float(dicount_value)

            if (not discount_sum) and price_sale:
                discount_sum = Decimal(int(price - price_sale))

            if price_sale:
                price_sale = Decimal(int(price_sale))

        return price_sale, discount_percent, discount_sum

    def get_offer_list(self, data):
        result = []
        if len(data["specialOffers"]):
            for offer in data["specialOffers"]:
                name = offer["name"]
                price = str(round(offer["discount"]["calculate"]["price"]))
                result.append(f"{name} {price}")
        return "; ".join(result) if len(result) else None

    def get_prices(self, data):
        price = self.dec_or_none(data["price"]["value"])
        price_sale = None

        if len(data["specialOffers"]):
            offer = data["specialOffers"][0]
            discount = offer["discount"]
            price_sale = discount["calculate"]["price"]
            price_sale = Decimal(int(price_sale)) if price_sale else None
            if price_sale == price:
                price_sale = None

        return price, price_sale

    def get_discount(self, price, sale_price):
        if price and sale_price:
            return price - sale_price
        return None

    def get_discount_percent(self, data):
        discount_percent = None
        if len(data["specialOffers"]):
            offer = data["specialOffers"][0]
            discount = offer["discount"]
            units = discount["unit"]

            dicount_value = discount["value"]
            if dicount_value:
                if units.lower() == "percent":
                    discount_percent = float(dicount_value)

        return discount_percent

    def get_sale_status(self, value):
        return {"AVAILABLE": "Свободно", "BOOKED": "Забронировано", "SOLD": "Продано"}[
            value
        ]

    def get_complex(self, project, address):
        region = address.split(",")[0]
        return f"{project} ({region})"

    def dec_or_none(self, value):
        return Decimal(value) if value else None

    def get_flat_url(self, data):
        return f"{self.host}#/profitbase/house/{data['house_id']}/list?propertyId={data['id']}"


class ApartmentParser(BaseParser):
    def parse(self, data):
        estate_obj = EstateObject()
        estate_obj.type = 'flat'
        estate_obj.complex = f"{data['projectName']} (Анапа)"

        estate_obj.floor = data['floor']
        if data['studio']:
            estate_obj.rooms = 'studio'
        else:
            estate_obj.rooms= data['rooms_amount']
        if data['status'] not in ['SOLD']:
            estate_obj.in_sale = 1
        if 'очередь' in data['houseName']:
            estate_obj.building = self.get_building(data['houseName'].split(',')[-1]).replace('№', '')
            estate_obj.phase = self.get_building(data['houseName'].split(',')[0].replace('очередь', ''))
        else:
            estate_obj.building = self.get_building(data['houseName']).replace('№', '')

        estate_obj.number = data['number']
        estate_obj.section = data['section'].lower().replace('секция', '')
        estate_obj.area = Decimal(data['area']['area_total'])
        if data['area']['area_living']:
            estate_obj.living_area = Decimal(data['area']['area_living'])
        estate_obj.plan = self.get_plan(data['planImages'])
        estate_obj.view = self.get_view(data)
        estate_obj.sale_status = self.get_sale_status(data['status'])
        estate_obj.finished = self.get_finished(data['custom_fields'])
        estate_obj.flat_url = self.get_flat_url(data)
        estate_obj.comissioning = self.comissions[data['house_id']]

        price, price_sale = self.get_prices(data)

        for element in data['custom_fields']:
            if 'Балкон' in element['name'] and element['value'] == 'Есть':
                estate_obj.feature = 'Балкон'
            if 'Цена при' in element['name']:
                price_sale = element['value']
                estate_obj.sale = (element['name'])

        if estate_obj.finished:
            estate_obj.price_finished = Decimal(price)
            if price_sale:
                estate_obj.price_finished_sale = Decimal(price_sale)
            estate_obj.finishing_name = self.get_finishing_name(data['custom_fields'])
        else:
            estate_obj.price_base = Decimal(price)
            if price_sale:
                estate_obj.price_sale = Decimal(price_sale)
        features = []
        for field in data['custom_fields']:
            if field['value'] and 'Есть' in str(field['value']):
                if 'Кухня-гостиная' in field['name']:
                    features.append('Кухня-гостиная')
                elif 'Теплая лоджия' in field['name']:
                    features.append('Теплая лоджия')
                elif 'Большая прихожая' in field['name']:
                    features.append('Большая прихожая')
                elif 'Второй санузел' in field['name']:
                    features.append('Второй санузел')
                elif 'Чистовая' in field['name']:
                    pass
                elif 'Гардеробная' in field['name']:
                    features.append('Гардеробная')
                elif 'Окна на две стороны' in field['name']:
                    features.append('Окна на две стороны')
                elif 'Вид' in field['name']:
                    estate_obj.view = field['name']
                elif 'Мастер-спальня' in field['name']:
                    features.append('Мастер-спальня')
                elif 'Балкон' in field['name']:
                    features.append('Балкон')
                elif 'Лоджия' in field['name']:
                    features.append('Лоджия')
                else:
                    raise Exception(f'New feature {field["name"]}')
        estate_obj.feature = features if features else None
        return estate_obj.__dict__


class CommercialParser(BaseParser):
    def parse(self, data):
        estate_obj = EstateObject()
        estate_obj.complex = f"{data['projectName']} (Анапа)"
        if 'очередь' in data['houseName']:
            estate_obj.phase = data['houseName'].split(' ')[0].replace('очередь', '')
        estate_obj.type = 'commercial'

        if data['status'] not in ['SOLD']:
            estate_obj.in_sale = 1
        if data['sectionName']:
            estate_obj.section = data['sectionName'].lower().replace('секция', '').strip()
        estate_obj.floor = data['floor']
        estate_obj.number = data['number'].strip()
        estate_obj.area = Decimal(data['area']['area_total'])
        estate_obj.plan = self.get_plan(data['planImages'])
        estate_obj.sale_status = self.get_sale_status(data['status'])
        estate_obj.flat_url = self.get_flat_url(data)
        estate_obj.building = data['houseName'].replace('Дом №', '')
        estate_obj.comissioning = self.comissions[data['house_id']]

        price, price_sale = self.get_prices(data)
        estate_obj.discount = self.get_discount(price, price_sale)
        estate_obj.discount_percent = self.get_discount_percent(data)
        estate_obj.price_base = price
        estate_obj.price_sale = price_sale
        return estate_obj.__dict__


class ParkingParser(BaseParser):
    def parse(self, data):
        estate_obj = EstateObject()

        estate_obj.complex = f"{data['projectName']} (Анапа)"
        estate_obj.type = 'storeroom'
        if data['status'] not in ['SOLD']:
            estate_obj.in_sale = 1
        if data['section'] != '_':
            estate_obj.section = self.get_section(data['section'].lower().replace('секция', ''))
        estate_obj.phase = None
        estate_obj.building = data['houseName'].replace('Дом №', '')
        if 'очередь' in data['houseName']:
            estate_obj.phase = data['houseName'].split('-')[-1].replace('очередь', '')
        estate_obj.floor = data['floor']
        estate_obj.number = data['number'].strip()
        estate_obj.area = Decimal(data['area']['area_total'])
        estate_obj.plan = self.get_plan(data['planImages'])
        estate_obj.sale_status = self.get_sale_status(data['status'])
        estate_obj.flat_url = self.get_flat_url(data)
        estate_obj.comissioning = self.comissions[data['house_id']]

        price, price_sale = self.get_prices(data)
        estate_obj.discount = self.get_discount(price, price_sale)
        estate_obj.discount_percent = self.get_discount_percent(data)
        estate_obj.price_base = price
        estate_obj.price_sale = price_sale

        return estate_obj.__dict__


"""
Fetch & dump methods

"""


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(o)


def dumpResult(results_dict):
    json.dump(results_dict, sys.stdout, indent=4, cls=DecimalEncoder)


def fetch_page(url, **kwargs):
    page = requests.get(url, **kwargs)
    # raise exception if resource unavailable else continues
    if not page.raise_for_status():
        return page


class Profitbase(object):
    def __init__(self, profitbase_id, host, api_version=4):
        self.profitbase_id = profitbase_id
        self.host = host
        self.api_version = api_version

    def update_token(self):
        url = f"https://{self.profitbase_id}.profitbase.ru/api/v{self.api_version}/json/authentication"
        payload = {
            "type": "external-site-widget",
            "credentials": {"referrer": self.host, "referer": self.host},
        }

        headers = {
            "Host": f"{self.profitbase_id}.profitbase.ru",
            "Connection": "keep-alive",
            "Content-Length": "123",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                AppleWebKit/537.36 (KHTML, like Gecko) \
                Chrome/89.0.4389.114 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "http://smart-catalog.profitbase.ru",
            "Referer": "http://smart-catalog.profitbase.ru/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        res = requests.post(url, data=json.dumps(payload), headers=headers)
        if 'access_token' not in res.json():
            return
        return res.json()["access_token"]

    def get_estate(self, token, prop_type, page_limit=100, **additional_params):
        url = f"http://{self.profitbase_id}.profitbase.ru/api/v{self.api_version}/json/property"
        params = {
            "propertyTypeAliases[0]": prop_type,
            "isHouseFinished": "0",
            "status[0]": "AVAILABLE",
            "access_token": token,
            "order[property_id]": "asc",
            "limit": page_limit,
            "offset": 0,
            "full": "true",
            "returnFilteredCount": "true",
        }

        headers = {
            "Host": f"{self.profitbase_id}.profitbase.ru",
            "Connection": "keep-alive",
            "Content-Length": "123",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                AppleWebKit/537.36 (KHTML, like Gecko) \
                Chrome/89.0.4389.114 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "http://smart-catalog.profitbase.ru",
            "Referer": "http://smart-catalog.profitbase.ru/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        for k, v in additional_params.items():
            params[k] = v

        result = []
        next_page = True

        while next_page:
            res = fetch_page(url, params=params, headers=headers).json()
            total_count = int(res["data"]["filteredCount"])
            result += res["data"]["properties"]
            params["offset"] += page_limit
            next_page = len(result) < total_count

        return result

    def format_comission(self, quarter, year):
        kv = {1: "I", 2: "II", 3: "III", 4: "IV"}[quarter]
        return f"{kv} кв {year}"

    def get_house_comissions(self, token):
        url = f"https://{self.profitbase_id}.profitbase.ru/api/v4/json/house"
        params = {"access_token": token}

        headers = {
            "Host": f"{self.profitbase_id}.profitbase.ru",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) \
                AppleWebKit/537.36 (KHTML, like Gecko) \
                Chrome/89.0.4389.114 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "http://smart-catalog.profitbase.ru",
            "Referer": "http://smart-catalog.profitbase.ru/",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        res = fetch_page(url, params=params).json()
        comissions = {}
        for house in res["data"]:
            state = house["buildingState"]
            end = house["developmentEndQuarter"]
            value = None
            if state == "HAND-OVER":
                value = "сдан"
            elif state == "UNFINISHED" and end:
                value = self.format_comission(end["quarter"], end["year"])
            comissions[house["id"]] = value
        return comissions


def has_price(estate_obj):
    return (
        estate_obj["price_base"]
        or estate_obj["price_finished"]
        or estate_obj["price_sale"]
        or estate_obj["price_finished_sale"]
    )


def get_data():
    pb = Profitbase("pb13246", "https://anapolisdom.ru/")
    token = pb.update_token()
    if not token:
        while not token:
            token = pb.update_token()
    comissions = pb.get_house_comissions(token)
    host = "https://anapolisdom.ru/"
    data = []

    flats = pb.get_estate(token, "property")
    parser = ApartmentParser(host, comissions)
    data += list(map(parser.parse, flats))
    commerce = pb.get_estate(token, "commercial_premises")
    parser = CommercialParser(host, comissions)
    data += list(map(parser.parse, commerce))
    parkings = pb.get_estate(token, "pantry")
    parser = ParkingParser(host, comissions)
    data += list(map(parser.parse, parkings))

    return list(filter(lambda e: has_price(e), data))


if __name__ == "__main__":
    dumpResult(get_data())
