from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional


class Constants:
    networks = [
        "local",
        "finney",
        "test",
        "archive",
        "subvortex",
        "rao",
        "dev",
        "latent-lite",
    ]
    finney_entrypoint = "wss://entrypoint-finney.opentensor.ai:443"
    finney_test_entrypoint = "wss://test.finney.opentensor.ai:443"
    archive_entrypoint = "wss://archive.chain.opentensor.ai:443"
    subvortex_entrypoint = "ws://subvortex.info:9944"
    local_entrypoint = "ws://127.0.0.1:9944"
    rao_entrypoint = "wss://rao.chain.opentensor.ai:443"
    dev_entrypoint = "wss://dev.chain.opentensor.ai:443"
    local_entrypoint = "ws://127.0.0.1:9944"
    latent_lite_entrypoint = "wss://lite.sub.latent.to:443"
    network_map = {
        "finney": finney_entrypoint,
        "test": finney_test_entrypoint,
        "archive": archive_entrypoint,
        "local": local_entrypoint,
        "dev": dev_entrypoint,
        "rao": rao_entrypoint,
        "latent-lite": latent_lite_entrypoint,
        "subvortex": subvortex_entrypoint,
    }
    genesis_block_hash_map = {
        "finney": "0x2f0555cc76fc2840a25a6ea3b9637146806f1f44b090c175ffde2a7e5ab36c03",
        "test": "0x8f9cf856bf558a14440e75569c9e58594757048d7b3a84b5d25f6bd978263105",
    }
    delegates_detail_url = "https://raw.githubusercontent.com/opentensor/bittensor-delegates/main/public/delegates.json"


@dataclass
class DelegatesDetails:
    display: str
    additional: list[tuple[str, str]]
    web: str
    legal: Optional[str] = None
    riot: Optional[str] = None
    email: Optional[str] = None
    pgp_fingerprint: Optional[str] = None
    image: Optional[str] = None
    twitter: Optional[str] = None

    @classmethod
    def from_chain_data(cls, data: dict[str, Any]) -> "DelegatesDetails":
        def decode(key: str, default=""):
            try:
                if isinstance(data.get(key), dict):
                    value = next(data.get(key).values())
                    return bytes(value[0]).decode("utf-8")
                elif isinstance(data.get(key), int):
                    return data.get(key)
                elif isinstance(data.get(key), tuple):
                    return bytes(data.get(key)[0]).decode("utf-8")
                else:
                    return default
            except (UnicodeDecodeError, TypeError):
                return default

        return cls(
            display=decode("display"),
            additional=decode("additional", []),
            web=decode("web"),
            legal=decode("legal"),
            riot=decode("riot"),
            email=decode("email"),
            pgp_fingerprint=decode("pgp_fingerprint", None),
            image=decode("image"),
            twitter=decode("twitter"),
        )


class Defaults:
    netuid = 1
    rate_tolerance = 0.005

    class config:
        base_path = "~/.bittensor"
        path = "~/.bittensor/config.yml"
        dictionary = {
            "network": None,
            "wallet_path": None,
            "wallet_name": None,
            "wallet_hotkey": None,
            "use_cache": True,
            "metagraph_cols": {
                "UID": True,
                "GLOBAL_STAKE": True,
                "LOCAL_STAKE": True,
                "STAKE_WEIGHT": True,
                "RANK": True,
                "TRUST": True,
                "CONSENSUS": True,
                "INCENTIVE": True,
                "DIVIDENDS": True,
                "EMISSION": True,
                "VTRUST": True,
                "VAL": True,
                "UPDATED": True,
                "ACTIVE": True,
                "AXON": True,
                "HOTKEY": True,
                "COLDKEY": True,
            },
        }

    class subtensor:
        network = "finney"
        chain_endpoint = None
        _mock = False

    class pow_register:
        num_processes = None
        update_interval = 50_000
        output_in_place = True
        verbose = False

        class cuda:
            dev_id = 0
            use_cuda = False
            tpb = 256

    class wallet:
        name = "default"
        hotkey = "default"
        path = "~/.bittensor/wallets/"

    class logging:
        debug = False
        trace = False
        record_log = False
        logging_dir = "~/.bittensor/miners"

    class dashboard:
        path = "~/.bittensor/dashboard/"


defaults = Defaults


class WalletOptions(Enum):
    PATH: str = "path"
    NAME: str = "name"
    HOTKEY: str = "hotkey"


class WalletValidationTypes(Enum):
    NONE = None
    WALLET = "wallet"
    WALLET_AND_HOTKEY = "wallet_and_hotkey"


TYPE_REGISTRY = {
    "types": {
        "Balance": "u64",  # Need to override default u128
    },
}

UNITS = [
    b"\xCE\xA4".decode(),  # Τ (Upper case Tau, 0)
    b"\xCE\xB1".decode(),  # α (Alpha, 1)
    b"\xCE\xB2".decode(),  # β (Beta, 2)
    b"\xCE\xB3".decode(),  # γ (Gamma, 3)
    b"\xCE\xB4".decode(),  # δ (Delta, 4)
    b"\xCE\xB5".decode(),  # ε (Epsilon, 5)
    b"\xCE\xB6".decode(),  # ζ (Zeta, 6)
    b"\xCE\xB7".decode(),  # η (Eta, 7)
    b"\xCE\xB8".decode(),  # θ (Theta, 8)
    b"\xCE\xB9".decode(),  # ι (Iota, 9)
    b"\xCE\xBA".decode(),  # κ (Kappa, 10)
    b"\xCE\xBB".decode(),  # λ (Lambda, 11)
    b"\xCE\xBC".decode(),  # μ (Mu, 12)
    b"\xCE\xBD".decode(),  # ν (Nu, 13)
    b"\xCE\xBE".decode(),  # ξ (Xi, 14)
    b"\xCE\xBF".decode(),  # ο (Omicron, 15)
    b"\xCF\x80".decode(),  # π (Pi, 16)
    b"\xCF\x81".decode(),  # ρ (Rho, 17)
    b"\xCF\x83".decode(),  # σ (Sigma, 18)
    "t",         # t (Tau, 19)
    b"\xCF\x85".decode(),  # υ (Upsilon, 20)
    b"\xCF\x86".decode(),  # φ (Phi, 21)
    b"\xCF\x87".decode(),  # χ (Chi, 22)
    b"\xCF\x88".decode(),  # ψ (Psi, 23)
    b"\xCF\x89".decode(),  # ω (Omega, 24)
    b"\xD7\x90".decode(),  # א (Aleph, 25)
    b"\xD7\x91".decode(),  # ב (Bet, 26)
    b"\xD7\x92".decode(),  # ג (Gimel, 27)
    b"\xD7\x93".decode(),  # ד (Dalet, 28)
    b"\xD7\x94".decode(),  # ה (He, 29)
    b"\xD7\x95".decode(),  # ו (Vav, 30)
    b"\xD7\x96".decode(),  # ז (Zayin, 31)
    b"\xD7\x97".decode(),  # ח (Het, 32)
    b"\xD7\x98".decode(),  # ט (Tet, 33)
    b"\xD7\x99".decode(),  # י (Yod, 34)
    b"\xD7\x9A".decode(),  # ך (Final Kaf, 35)
    b"\xD7\x9B".decode(),  # כ (Kaf, 36)
    b"\xD7\x9C".decode(),  # ל (Lamed, 37)
    b"\xD7\x9D".decode(),  # ם (Final Mem, 38)
    b"\xD7\x9E".decode(),  # מ (Mem, 39)
    b"\xD7\x9F".decode(),  # ן (Final Nun, 40)
    b"\xD7\xA0".decode(),  # נ (Nun, 41)
    b"\xD7\xA1".decode(),  # ס (Samekh, 42)
    b"\xD7\xA2".decode(),  # ע (Ayin, 43)
    b"\xD7\xA3".decode(),  # ף (Final Pe, 44)
    b"\xD7\xA4".decode(),  # פ (Pe, 45)
    b"\xD7\xA5".decode(),  # ץ (Final Tsadi, 46)
    b"\xD7\xA6".decode(),  # צ (Tsadi, 47)
    b"\xD7\xA7".decode(),  # ק (Qof, 48)
    b"\xD7\xA8".decode(),  # ר (Resh, 49)
    b"\xD7\xA9".decode(),  # ש (Shin, 50)
    b"\xD7\xAA".decode(),  # ת (Tav, 51)
    b"\xD8\xA7".decode(),  # ا (Alif, 52)
    b"\xD8\xA8".decode(),  # ب (Ba, 53)
    b"\xD8\xAA".decode(),  # ت (Ta, 54)
    b"\xD8\xAB".decode(),  # ث (Tha, 55)
    b"\xD8\xAC".decode(),  # ج (Jim, 56)
    b"\xD8\xAD".decode(),  # ح (Ha, 57)
    b"\xD8\xAE".decode(),  # خ (Kha, 58)
    b"\xD8\xAF".decode(),  # د (Dal, 59)
    b"\xD8\xB0".decode(),  # ذ (Dhal, 60)
    b"\xD8\xB1".decode(),  # ر (Ra, 61)
    b"\xD8\xB2".decode(),  # ز (Zay, 62)
    b"\xD8\xB3".decode(),  # س (Sin, 63)
    b"\xD8\xB4".decode(),  # ش (Shin, 64)
    b"\xD8\xB5".decode(),  # ص (Sad, 65)
    b"\xD8\xB6".decode(),  # ض (Dad, 66)
    b"\xD8\xB7".decode(),  # ط (Ta, 67)
    b"\xD8\xB8".decode(),  # ظ (Dha, 68)
    b"\xD8\xB9".decode(),  # ع (Ain, 69)
    b"\xD8\xBA".decode(),  # غ (Ghayn, 70)
    b"\xD9\x81".decode(),  # ف (Fa, 71)
    b"\xD9\x82".decode(),  # ق (Qaf, 72)
    b"\xD9\x83".decode(),  # ك (Kaf, 73)
    b"\xD9\x84".decode(),  # ل (Lam, 74)
    b"\xD9\x85".decode(),  # م (Mim, 75)
    b"\xD9\x86".decode(),  # ن (Nun, 76)
    b"\xD9\x87".decode(),  # ه (Ha, 77)
    b"\xD9\x88".decode(),  # و (Waw, 78)
    b"\xD9\x8A".decode(),  # ي (Ya, 79)
    b"\xD9\x89".decode(),  # ى (Alef Maksura, 80)
    b"\xE1\x9A\xA0".decode(),  # ᚠ (Fehu, wealth, 81)
    b"\xE1\x9A\xA2".decode(),  # ᚢ (Uruz, strength, 82)
    b"\xE1\x9A\xA6".decode(),  # ᚦ (Thurisaz, giant, 83)
    b"\xE1\x9A\xA8".decode(),  # ᚨ (Ansuz, god, 84)
    b"\xE1\x9A\xB1".decode(),  # ᚱ (Raidho, ride, 85)
    b"\xE1\x9A\xB3".decode(),  # ᚲ (Kaunan, ulcer, 86)
    b"\xD0\xAB".decode(),     # Ы (Cyrillic Yeru, 87)
    b"\xE1\x9B\x89".decode(),  # ᛉ (Algiz, protection, 88)
    b"\xE1\x9B\x92".decode(),  # ᛒ (Berkanan, birch, 89)
    b"\xE1\x9A\x80".decode(),  #   (Space, 90)
    b"\xE1\x9A\x81".decode(),  # ᚁ (Beith, birch, 91)
    b"\xE1\x9A\x82".decode(),  # ᚂ (Luis, rowan, 92)
    b"\xE1\x9A\x83".decode(),  # ᚃ (Fearn, alder, 93)
    b"\xE1\x9A\x84".decode(),  # ᚄ (Sail, willow, 94)
    b"\xE1\x9A\x85".decode(),  # ᚅ (Nion, ash, 95)
    b"\xE1\x9A\x9B".decode(),  # ᚛ (Forfeda, 96)
    b"\xE1\x83\x90".decode(),  # ა (Ani, 97)
    b"\xE1\x83\x91".decode(),  # ბ (Bani, 98)
    b"\xE1\x83\x92".decode(),  # გ (Gani, 99)
    b"\xE1\x83\x93".decode(),  # დ (Doni, 100)
    b"\xE1\x83\x94".decode(),  # ე (Eni, 101)
    b"\xE1\x83\x95".decode(),  # ვ (Vini, 102)
    b"\xD4\xB1".decode(),      # Ա (Ayp, 103)
    b"\xD4\xB2".decode(),      # Բ (Ben, 104)
    b"\xD4\xB3".decode(),      # Գ (Gim, 105)
    b"\xD4\xB4".decode(),      # Դ (Da, 106)
    b"\xD4\xB5".decode(),      # Ե (Ech, 107)
    b"\xD4\xB6".decode(),      # Զ (Za, 108)
    b"\xD5\x9E".decode(),      # ՞ (Question mark, 109)
    b"\xD0\x80".decode(),      # Ѐ (Ie with grave, 110)
    b"\xD0\x81".decode(),      # Ё (Io, 111)
    b"\xD0\x82".decode(),      # Ђ (Dje, 112)
    b"\xD0\x83".decode(),      # Ѓ (Gje, 113)
    b"\xD0\x84".decode(),      # Є (Ukrainian Ie, 114)
    b"\xD0\x85".decode(),      # Ѕ (Dze, 115)
    b"\xD1\x8A".decode(),      # Ъ (Hard sign, 116)
    b"\xE2\xB2\x80".decode(),  # Ⲁ (Alfa, 117)
    b"\xE2\xB2\x81".decode(),  # ⲁ (Small Alfa, 118)
    b"\xE2\xB2\x82".decode(),  # Ⲃ (Vida, 119)
    b"\xE2\xB2\x83".decode(),  # ⲃ (Small Vida, 120)
    b"\xE2\xB2\x84".decode(),  # Ⲅ (Gamma, 121)
    b"\xE2\xB2\x85".decode(),  # ⲅ (Small Gamma, 122)
    b"\xF0\x91\x80\x80".decode(),  # 𑀀 (A, 123)
    b"\xF0\x91\x80\x81".decode(),  # 𑀁 (Aa, 124)
    b"\xF0\x91\x80\x82".decode(),  # 𑀂 (I, 125)
    b"\xF0\x91\x80\x83".decode(),  # 𑀃 (Ii, 126)
    b"\xF0\x91\x80\x85".decode(),  # 𑀅 (U, 127)
    b"\xE0\xB6\xB1".decode(),       # ඲ (La, 128)
    b"\xE0\xB6\xB2".decode(),       # ඳ (Va, 129)
    b"\xE0\xB6\xB3".decode(),       # ප (Sha, 130)
    b"\xE0\xB6\xB4".decode(),       # ඵ (Ssa, 131)
    b"\xE0\xB6\xB5".decode(),       # බ (Sa, 132)
    b"\xE0\xB6\xB6".decode(),       # භ (Ha, 133)
    b"\xE2\xB0\x80".decode(),       # Ⰰ (Az, 134)
    b"\xE2\xB0\x81".decode(),       # Ⰱ (Buky, 135)
    b"\xE2\xB0\x82".decode(),       # Ⰲ (Vede, 136)
    b"\xE2\xB0\x83".decode(),       # Ⰳ (Glagoli, 137)
    b"\xE2\xB0\x84".decode(),       # Ⰴ (Dobro, 138)
    b"\xE2\xB0\x85".decode(),       # Ⰵ (Yest, 139)
    b"\xE2\xB0\x86".decode(),       # Ⰶ (Zhivete, 140)
    b"\xE2\xB0\x87".decode(),       # Ⰷ (Zemlja, 141)
    b"\xE2\xB0\x88".decode(),       # Ⰸ (Izhe, 142)
    b"\xE2\xB0\x89".decode(),       # Ⰹ (Initial Izhe, 143)
    b"\xE2\xB0\x8A".decode(),       # Ⰺ (I, 144)
    b"\xE2\xB0\x8B".decode(),       # Ⰻ (Djerv, 145)
    b"\xE2\xB0\x8C".decode(),       # Ⰼ (Kako, 146)
    b"\xE2\xB0\x8D".decode(),       # Ⰽ (Ljudije, 147)
    b"\xE2\xB0\x8E".decode(),       # Ⰾ (Myse, 148)
    b"\xE2\xB0\x8F".decode(),       # Ⰿ (Nash, 149)
    b"\xE2\xB0\x90".decode(),       # Ⱀ (On, 150)
    b"\xE2\xB0\x91".decode(),       # Ⱁ (Pokoj, 151)
    b"\xE2\xB0\x92".decode(),       # Ⱂ (Rtsy, 152)
    b"\xE2\xB0\x93".decode(),       # Ⱃ (Slovo, 153)
    b"\xE2\xB0\x94".decode(),       # Ⱄ (Tvrido, 154)
    b"\xE2\xB0\x95".decode(),       # Ⱅ (Uku, 155)
    b"\xE2\xB0\x96".decode(),       # Ⱆ (Fert, 156)
    b"\xE2\xB0\x97".decode(),       # Ⱇ (Xrivi, 157)
    b"\xE2\xB0\x98".decode(),       # Ⱈ (Ot, 158)
    b"\xE2\xB0\x99".decode(),       # Ⱉ (Cy, 159)
    b"\xE2\xB0\x9A".decode(),       # Ⱊ (Shcha, 160)
    b"\xE2\xB0\x9B".decode(),       # Ⱋ (Er, 161)
    b"\xE2\xB0\x9C".decode(),       # Ⱌ (Yeru, 162)
    b"\xE2\xB0\x9D".decode(),       # Ⱍ (Small Yer, 163)
    b"\xE2\xB0\x9E".decode(),       # Ⱎ (Yo, 164)
    b"\xE2\xB0\x9F".decode(),       # Ⱏ (Yu, 165)
    b"\xE2\xB0\xA0".decode(),       # Ⱐ (Ja, 166)
    b"\xE0\xB8\x81".decode(),       # ก (Ko Kai, 167)
    b"\xE0\xB8\x82".decode(),       # ข (Kho Khai, 168)
    b"\xE0\xB8\x83".decode(),       # ฃ (Kho Khuat, 169)
    b"\xE0\xB8\x84".decode(),       # ค (Kho Khon, 170)
    b"\xE0\xB8\x85".decode(),       # ฅ (Kho Rakhang, 171)
    b"\xE0\xB8\x86".decode(),       # ฆ (Kho Khwai, 172)
    b"\xE0\xB8\x87".decode(),       # ง (Ngo Ngu, 173)
    b"\xE0\xB8\x88".decode(),       # จ (Cho Chan, 174)
    b"\xE0\xB8\x89".decode(),       # ฉ (Cho Ching, 175)
    b"\xE0\xB8\x8A".decode(),       # ช (Cho Chang, 176)
    b"\xE0\xB8\x8B".decode(),       # ซ (So So, 177)
    b"\xE0\xB8\x8C".decode(),       # ฌ (Cho Choe, 178)
    b"\xE0\xB8\x8D".decode(),       # ญ (Yo Ying, 179)
    b"\xE0\xB8\x8E".decode(),       # ฎ (Do Chada, 180)
    b"\xE0\xB8\x8F".decode(),       # ฏ (To Patak, 181)
    b"\xE0\xB8\x90".decode(),       # ฐ (Tho Than, 182)
    b"\xE0\xB8\x91".decode(),       # ฑ (Tho Nangmontho, 183)
    b"\xE0\xB8\x92".decode(),       # ฒ (Tho Phuthao, 184)
    b"\xE0\xB8\x93".decode(),       # ณ (No Nen, 185)
    b"\xE0\xB8\x94".decode(),       # ด (Do Dek, 186)
    b"\xE0\xB8\x95".decode(),       # ต (To Tao, 187)
    b"\xE0\xB8\x96".decode(),       # ถ (Tho Thung, 188)
    b"\xE0\xB8\x97".decode(),       # ท (Tho Thahan, 189)
    b"\xE0\xB8\x98".decode(),       # ธ (Tho Thong, 190)
    b"\xE0\xB8\x99".decode(),       # น (No Nu, 191)
    b"\xE0\xB8\x9A".decode(),       # บ (Bo Baimai, 192)
    b"\xE0\xB8\x9B".decode(),       # ป (Po Pla, 193)
    b"\xE0\xB8\x9C".decode(),       # ผ (Pho Phung, 194)
    b"\xE0\xB8\x9D".decode(),       # ฝ (Fo Fa, 195)
    b"\xE0\xB8\x9E".decode(),       # พ (Pho Phan, 196)
    b"\xE0\xB8\x9F".decode(),       # ฟ (Fo Fan, 197)
    b"\xE0\xB8\xA0".decode(),       # ภ (Pho Samphao, 198)
    b"\xE0\xB8\xA1".decode(),       # ม (Mo Ma, 199)
    b"\xE0\xB8\xA2".decode(),       # ย (Yo Yak, 200)
    b"\xE0\xB8\xA3".decode(),       # ร (Ro Rua, 201)
    b"\xE0\xB8\xA5".decode(),       # ล (Lo Ling, 202)
    b"\xE0\xB8\xA7".decode(),       # ว (Wo Waen, 203)
    b"\xE0\xB8\xA8".decode(),       # ศ (So Sala, 204)
    b"\xE0\xB8\xA9".decode(),       # ษ (So Rusi, 205)
    b"\xE0\xB8\xAA".decode(),       # ส (So Sua, 206)
    b"\xE0\xB8\xAB".decode(),       # ห (Ho Hip, 207)
    b"\xE0\xB8\xAC".decode(),       # ฬ (Lo Chula, 208)
    b"\xE0\xB8\xAD".decode(),       # อ (O Ang, 209)
    b"\xE0\xB8\xAE".decode(),       # ฮ (Ho Nokhuk, 210)
    b"\xE1\x84\x80".decode(),       # ㄱ (Giyeok, 211)
    b"\xE1\x84\x81".decode(),       # ㄴ (Nieun, 212)
    b"\xE1\x84\x82".decode(),       # ㄷ (Digeut, 213)
    b"\xE1\x84\x83".decode(),       # ㄹ (Rieul, 214)
    b"\xE1\x84\x84".decode(),       # ㅁ (Mieum, 215)
    b"\xE1\x84\x85".decode(),       # ㅂ (Bieup, 216)
    b"\xE1\x84\x86".decode(),       # ㅅ (Siot, 217)
    b"\xE1\x84\x87".decode(),       # ㅇ (Ieung, 218)
    b"\xE1\x84\x88".decode(),       # ㅈ (Jieut, 219)
    b"\xE1\x84\x89".decode(),       # ㅊ (Chieut, 220)
    b"\xE1\x84\x8A".decode(),       # ㅋ (Kieuk, 221)
    b"\xE1\x84\x8B".decode(),       # ㅌ (Tieut, 222)
    b"\xE1\x84\x8C".decode(),       # ㅍ (Pieup, 223)
    b"\xE1\x84\x8D".decode(),       # ㅎ (Hieut, 224)
    b"\xE1\x85\xA1".decode(),       # ㅏ (A, 225)
    b"\xE1\x85\xA2".decode(),       # ㅐ (Ae, 226)
    b"\xE1\x85\xA3".decode(),       # ㅑ (Ya, 227)
    b"\xE1\x85\xA4".decode(),       # ㅒ (Yae, 228)
    b"\xE1\x85\xA5".decode(),       # ㅓ (Eo, 229)
    b"\xE1\x85\xA6".decode(),       # ㅔ (E, 230)
    b"\xE1\x85\xA7".decode(),       # ㅕ (Yeo, 231)
    b"\xE1\x85\xA8".decode(),       # ㅖ (Ye, 232)
    b"\xE1\x85\xA9".decode(),       # ㅗ (O, 233)
    b"\xE1\x85\xAA".decode(),       # ㅘ (Wa, 234)
    b"\xE1\x85\xAB".decode(),       # ㅙ (Wae, 235)
    b"\xE1\x85\xAC".decode(),       # ㅚ (Oe, 236)
    b"\xE1\x85\xAD".decode(),       # ㅛ (Yo, 237)
    b"\xE1\x85\xAE".decode(),       # ㅜ (U, 238)
    b"\xE1\x85\xAF".decode(),       # ㅝ (Weo, 239)
    b"\xE1\x85\xB0".decode(),       # ㅞ (We, 240)
    b"\xE1\x85\xB1".decode(),       # ㅟ (Wi, 241)
    b"\xE1\x85\xB2".decode(),       # ㅠ (Yu, 242)
    b"\xE1\x85\xB3".decode(),       # ㅡ (Eu, 243)
    b"\xE1\x85\xB4".decode(),       # ㅢ (Ui, 244)
    b"\xE1\x85\xB5".decode(),       # ㅣ (I, 245)
    b"\xE1\x8A\xA0".decode(),       # አ (Glottal A, 246)
    b"\xE1\x8A\xA1".decode(),       # ኡ (Glottal U, 247)
    b"\xE1\x8A\xA2".decode(),       # ኢ (Glottal I, 248)
    b"\xE1\x8A\xA3".decode(),       # ኣ (Glottal Aa, 249)
    b"\xE1\x8A\xA4".decode(),       # ኤ (Glottal E, 250)
    b"\xE1\x8A\xA5".decode(),       # እ (Glottal Ie, 251)
    b"\xE1\x8A\xA6".decode(),       # ኦ (Glottal O, 252)
    b"\xE1\x8A\xA7".decode(),       # ኧ (Glottal Wa, 253)
    b"\xE1\x8B\x88".decode(),       # ወ (Wa, 254)
    b"\xE1\x8B\x89".decode(),       # ዉ (Wu, 255)
    b"\xE1\x8B\x8A".decode(),       # ዊ (Wi, 256)
    b"\xE1\x8B\x8B".decode(),       # ዋ (Waa, 257)
    b"\xE1\x8B\x8C".decode(),       # ዌ (We, 258)
    b"\xE1\x8B\x8D".decode(),       # ው (Wye, 259)
    b"\xE1\x8B\x8E".decode(),       # ዎ (Wo, 260)
    b"\xE1\x8A\xB0".decode(),       # ኰ (Ko, 261)
    b"\xE1\x8A\xB1".decode(),       # ኱ (Ku, 262)
    b"\xE1\x8A\xB2".decode(),       # ኲ (Ki, 263)
    b"\xE1\x8A\xB3".decode(),       # ኳ (Kua, 264)
    b"\xE1\x8A\xB4".decode(),       # ኴ (Ke, 265)
    b"\xE1\x8A\xB5".decode(),       # ኵ (Kwe, 266)
    b"\xE1\x8A\xB6".decode(),       # ኶ (Ko, 267)
    b"\xE1\x8A\x90".decode(),       # ጐ (Go, 268)
    b"\xE1\x8A\x91".decode(),       # ጑ (Gu, 269)
    b"\xE1\x8A\x92".decode(),       # ጒ (Gi, 270)
    b"\xE1\x8A\x93".decode(),       # መ (Gua, 271)
    b"\xE1\x8A\x94".decode(),       # ጔ (Ge, 272)
    b"\xE1\x8A\x95".decode(),       # ጕ (Gwe, 273)
    b"\xE1\x8A\x96".decode(),       # ጖ (Go, 274)
    b"\xE0\xA4\x85".decode(),       # अ (A, 275)
    b"\xE0\xA4\x86".decode(),       # आ (Aa, 276)
    b"\xE0\xA4\x87".decode(),       # इ (I, 277)
    b"\xE0\xA4\x88".decode(),       # ई (Ii, 278)
    b"\xE0\xA4\x89".decode(),       # उ (U, 279)
    b"\xE0\xA4\x8A".decode(),       # ऊ (Uu, 280)
    b"\xE0\xA4\x8B".decode(),       # ऋ (R, 281)
    b"\xE0\xA4\x8F".decode(),       # ए (E, 282)
    b"\xE0\xA4\x90".decode(),       # ऐ (Ai, 283)
    b"\xE0\xA4\x93".decode(),       # ओ (O, 284)
    b"\xE0\xA4\x94".decode(),       # औ (Au, 285)
    b"\xE0\xA4\x95".decode(),       # क (Ka, 286)
    b"\xE0\xA4\x96".decode(),       # ख (Kha, 287)
    b"\xE0\xA4\x97".decode(),       # ग (Ga, 288)
    b"\xE0\xA4\x98".decode(),       # घ (Gha, 289)
    b"\xE0\xA4\x99".decode(),       # ङ (Nga, 290)
    b"\xE0\xA4\x9A".decode(),       # च (Cha, 291)
    b"\xE0\xA4\x9B".decode(),       # छ (Chha, 292)
    b"\xE0\xA4\x9C".decode(),       # ज (Ja, 293)
    b"\xE0\xA4\x9D".decode(),       # झ (Jha, 294)
    b"\xE0\xA4\x9E".decode(),       # ञ (Nya, 295)
    b"\xE0\xA4\x9F".decode(),       # ट (Ta, 296)
    b"\xE0\xA4\xA0".decode(),       # ठ (Tha, 297)
    b"\xE0\xA4\xA1".decode(),       # ड (Da, 298)
    b"\xE0\xA4\xA2".decode(),       # ढ (Dha, 299)
    b"\xE0\xA4\xA3".decode(),       # ण (Na, 300)
    b"\xE0\xA4\xA4".decode(),       # त (Ta, 301)
    b"\xE0\xA4\xA5".decode(),       # थ (Tha, 302)
    b"\xE0\xA4\xA6".decode(),       # द (Da, 303)
    b"\xE0\xA4\xA7".decode(),       # ध (Dha, 304)
    b"\xE0\xA4\xA8".decode(),       # न (Na, 305)
    b"\xE0\xA4\xAA".decode(),       # प (Pa, 306)
    b"\xE0\xA4\xAB".decode(),       # फ (Pha, 307)
    b"\xE0\xA4\xAC".decode(),       # ब (Ba, 308)
    b"\xE0\xA4\xAD".decode(),       # भ (Bha, 309)
    b"\xE0\xA4\xAE".decode(),       # म (Ma, 310)
    b"\xE0\xA4\xAF".decode(),       # य (Ya, 311)
    b"\xE0\xA4\xB0".decode(),       # र (Ra, 312)
    b"\xE0\xA4\xB2".decode(),       # ल (La, 313)
    b"\xE0\xA4\xB5".decode(),       # व (Va, 314)
    b"\xE0\xA4\xB6".decode(),       # श (Sha, 315)
    b"\xE0\xA4\xB7".decode(),       # ष (Ssa, 316)
    b"\xE0\xA4\xB8".decode(),       # स (Sa, 317)
    b"\xE0\xA4\xB9".decode(),       # ह (Ha, 318)
    b"\xE3\x82\xA2".decode(),       # ア (A, 319)
    b"\xE3\x82\xA4".decode(),       # イ (I, 320)
    b"\xE3\x82\xA6".decode(),       # ウ (U, 321)
    b"\xE3\x82\xA8".decode(),       # エ (E, 322)
    b"\xE3\x82\xAA".decode(),       # オ (O, 323)
    b"\xE3\x82\xAB".decode(),       # カ (Ka, 324)
    b"\xE3\x82\xAD".decode(),       # キ (Ki, 325)
    b"\xE3\x82\xAF".decode(),       # ク (Ku, 326)
    b"\xE3\x82\xB1".decode(),       # ケ (Ke, 327)
    b"\xE3\x82\xB3".decode(),       # コ (Ko, 328)
    b"\xE3\x82\xB5".decode(),       # サ (Sa, 329)
    b"\xE3\x82\xB7".decode(),       # シ (Shi, 330)
    b"\xE3\x82\xB9".decode(),       # ス (Su, 331)
    b"\xE3\x82\xBB".decode(),       # セ (Se, 332)
    b"\xE3\x82\xBD".decode(),       # ソ (So, 333)
    b"\xE3\x82\xBF".decode(),       # タ (Ta, 334)
    b"\xE3\x83\x81".decode(),       # チ (Chi, 335)
    b"\xE3\x83\x84".decode(),       # ツ (Tsu, 336)
    b"\xE3\x83\x86".decode(),       # テ (Te, 337)
    b"\xE3\x83\x88".decode(),       # ト (To, 338)
    b"\xE3\x83\x8A".decode(),       # ナ (Na, 339)
    b"\xE3\x83\x8B".decode(),       # ニ (Ni, 340)
    b"\xE3\x83\x8C".decode(),       # ヌ (Nu, 341)
    b"\xE3\x83\x8D".decode(),       # ネ (Ne, 342)
    b"\xE3\x83\x8E".decode(),       # ノ (No, 343)
    b"\xE3\x83\x8F".decode(),       # ハ (Ha, 344)
    b"\xE3\x83\x92".decode(),       # ヒ (Hi, 345)
    b"\xE3\x83\x95".decode(),       # フ (Fu, 346)
    b"\xE3\x83\x98".decode(),       # ヘ (He, 347)
    b"\xE3\x83\x9B".decode(),       # ホ (Ho, 348)
    b"\xE3\x83\x9E".decode(),       # マ (Ma, 349)
    b"\xE3\x83\x9F".decode(),       # ミ (Mi, 350)
    b"\xE3\x83\xA0".decode(),       # ム (Mu, 351)
    b"\xE3\x83\xA1".decode(),       # メ (Me, 352)
    b"\xE3\x83\xA2".decode(),       # モ (Mo, 353)
    b"\xE3\x83\xA4".decode(),       # ヤ (Ya, 354)
    b"\xE3\x83\xA6".decode(),       # ユ (Yu, 355)
    b"\xE3\x83\xA8".decode(),       # ヨ (Yo, 356)
    b"\xE3\x83\xA9".decode(),       # ラ (Ra, 357)
    b"\xE3\x83\xAA".decode(),       # リ (Ri, 358)
    b"\xE3\x83\xAB".decode(),       # ル (Ru, 359)
    b"\xE3\x83\xAC".decode(),       # レ (Re, 360)
    b"\xE3\x83\xAD".decode(),       # ロ (Ro, 361)
    b"\xE3\x83\xAF".decode(),       # ワ (Wa, 362)
    b"\xE3\x83\xB2".decode(),       # ヲ (Wo, 363)
    b"\xE3\x83\xB3".decode(),       # ン (N, 364)
    b"\xE2\xB4\xB0".decode(),       # ⴰ (Ya, 365)
    b"\xE2\xB4\xB1".decode(),       # ⴱ (Yab, 366)
    b"\xE2\xB4\xB2".decode(),       # ⴲ (Yabh, 367)
    b"\xE2\xB4\xB3".decode(),       # ⴳ (Yag, 368)
    b"\xE2\xB4\xB4".decode(),       # ⴴ (Yagh, 369)
    b"\xE2\xB4\xB5".decode(),       # ⴵ (Yaj, 370)
    b"\xE2\xB4\xB6".decode(),       # ⴶ (Yach, 371)
    b"\xE2\xB4\xB7".decode(),       # ⴷ (Yad, 372)
    b"\xE2\xB4\xB8".decode(),       # ⴸ (Yadh, 373)
    b"\xE2\xB4\xB9".decode(),       # ⴹ (Yadh, emphatic, 374)
    b"\xE2\xB4\xBA".decode(),       # ⴺ (Yaz, 375)
    b"\xE2\xB4\xBB".decode(),       # ⴻ (Yazh, 376)
    b"\xE2\xB4\xBC".decode(),       # ⴼ (Yaf, 377)
    b"\xE2\xB4\xBD".decode(),       # ⴽ (Yak, 378)
    b"\xE2\xB4\xBE".decode(),       # ⴾ (Yak, variant, 379)
    b"\xE2\xB4\xBF".decode(),       # ⴿ (Yaq, 380)
    b"\xE2\xB5\x80".decode(),       # ⵀ (Yah, 381)
    b"\xE2\xB5\x81".decode(),       # ⵁ (Yahh, 382)
    b"\xE2\xB5\x82".decode(),       # ⵂ (Yahl, 383)
    b"\xE2\xB5\x83".decode(),       # ⵃ (Yahm, 384)
    b"\xE2\xB5\x84".decode(),       # ⵄ (Yayn, 385)
    b"\xE2\xB5\x85".decode(),       # ⵅ (Yakh, 386)
    b"\xE2\xB5\x86".decode(),       # ⵆ (Yakl, 387)
    b"\xE2\xB5\x87".decode(),       # ⵇ (Yahq, 388)
    b"\xE2\xB5\x88".decode(),       # ⵈ (Yash, 389)
    b"\xE2\xB5\x89".decode(),       # ⵉ (Yi, 390)
    b"\xE2\xB5\x8A".decode(),       # ⵊ (Yij, 391)
    b"\xE2\xB5\x8B".decode(),       # ⵋ (Yizh, 392)
    b"\xE2\xB5\x8C".decode(),       # ⵌ (Yink, 393)
    b"\xE2\xB5\x8D".decode(),       # ⵍ (Yal, 394)
    b"\xE2\xB5\x8E".decode(),       # ⵎ (Yam, 395)
    b"\xE2\xB5\x8F".decode(),       # ⵏ (Yan, 396)
    b"\xE2\xB5\x90".decode(),       # ⵐ (Yang, 397)
    b"\xE2\xB5\x91".decode(),       # ⵑ (Yany, 398)
    b"\xE2\xB5\x92".decode(),       # ⵒ (Yap, 399)
    b"\xE2\xB5\x93".decode(),       # ⵓ (Yu, 400)
    b"\xE0\xB6\x85".decode(),       # අ (A, 401)
    b"\xE0\xB6\x86".decode(),       # ආ (Aa, 402)
    b"\xE0\xB6\x87".decode(),       # ඉ (I, 403)
    b"\xE0\xB6\x88".decode(),       # ඊ (Ii, 404)
    b"\xE0\xB6\x89".decode(),       # උ (U, 405)
    b"\xE0\xB6\x8A".decode(),       # ඌ (Uu, 406)
    b"\xE0\xB6\x8B".decode(),       # ඍ (R, 407)
    b"\xE0\xB6\x8C".decode(),       # ඎ (Rr, 408)
    b"\xE0\xB6\x8F".decode(),       # ඏ (L, 409)
    b"\xE0\xB6\x90".decode(),       # ඐ (Ll, 410)
    b"\xE0\xB6\x91".decode(),       # එ (E, 411)
    b"\xE0\xB6\x92".decode(),       # ඒ (Ee, 412)
    b"\xE0\xB6\x93".decode(),       # ඓ (Ai, 413)
    b"\xE0\xB6\x94".decode(),       # ඔ (O, 414)
    b"\xE0\xB6\x95".decode(),       # ඕ (Oo, 415)
    b"\xE0\xB6\x96".decode(),       # ඖ (Au, 416)
    b"\xE0\xB6\x9A".decode(),       # ක (Ka, 417)
    b"\xE0\xB6\x9B".decode(),       # ඛ (Kha, 418)
    b"\xE0\xB6\x9C".decode(),       # ග (Ga, 419)
    b"\xE0\xB6\x9D".decode(),       # ඝ (Gha, 420)
    b"\xE0\xB6\x9E".decode(),       # ඞ (Nga, 421)
    b"\xE0\xB6\x9F".decode(),       # ච (Cha, 422)
    b"\xE0\xB6\xA0".decode(),       # ඡ (Chha, 423)
    b"\xE0\xB6\xA1".decode(),       # ජ (Ja, 424)
    b"\xE0\xB6\xA2".decode(),       # ඣ (Jha, 425)
    b"\xE0\xB6\xA3".decode(),       # ඤ (Nya, 426)
    b"\xE0\xB6\xA4".decode(),       # ට (Ta, 427)
    b"\xE0\xB6\xA5".decode(),       # ඥ (Tha, 428)
    b"\xE0\xB6\xA6".decode(),       # ඦ (Da, 429)
    b"\xE0\xB6\xA7".decode(),       # ට (Dha, 430)
    b"\xE0\xB6\xA8".decode(),       # ඨ (Na, 431)
    b"\xE0\xB6\xAA".decode(),       # ඪ (Pa, 432)
    b"\xE0\xB6\xAB".decode(),       # ණ (Pha, 433)
    b"\xE0\xB6\xAC".decode(),       # ඬ (Ba, 434)
    b"\xE0\xB6\xAD".decode(),       # ත (Bha, 435)
    b"\xE0\xB6\xAE".decode(),       # ථ (Ma, 436)
    b"\xE0\xB6\xAF".decode(),       # ද (Ya, 437)
    b"\xE0\xB6\xB0".decode(),       # ධ (Ra, 438)

]

NETWORK_EXPLORER_MAP = {
    "opentensor": {
        "local": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "endpoint": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "finney": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
    },
    "taostats": {
        "local": "https://x.taostats.io",
        "endpoint": "https://x.taostats.io",
        "finney": "https://x.taostats.io",
    },
}


HYPERPARAMS = {
    # btcli name: (subtensor method, root-only bool)
    "rho": ("sudo_set_rho", False),
    "kappa": ("sudo_set_kappa", False),
    "immunity_period": ("sudo_set_immunity_period", False),
    "min_allowed_weights": ("sudo_set_min_allowed_weights", False),
    "max_weights_limit": ("sudo_set_max_weight_limit", False),
    "tempo": ("sudo_set_tempo", True),
    "min_difficulty": ("sudo_set_min_difficulty", False),
    "max_difficulty": ("sudo_set_max_difficulty", False),
    "weights_version": ("sudo_set_weights_version_key", False),
    "weights_rate_limit": ("sudo_set_weights_set_rate_limit", False),
    "adjustment_interval": ("sudo_set_adjustment_interval", True),
    "activity_cutoff": ("sudo_set_activity_cutoff", False),
    "target_regs_per_interval": ("sudo_set_target_registrations_per_interval", True),
    "min_burn": ("sudo_set_min_burn", True),
    "max_burn": ("sudo_set_max_burn", False),
    "bonds_moving_avg": ("sudo_set_bonds_moving_average", False),
    "max_regs_per_block": ("sudo_set_max_registrations_per_block", True),
    "serving_rate_limit": ("sudo_set_serving_rate_limit", False),
    "max_validators": ("sudo_set_max_allowed_validators", True),
    "adjustment_alpha": ("sudo_set_adjustment_alpha", False),
    "difficulty": ("sudo_set_difficulty", False),
    "commit_reveal_period": (
        "sudo_set_commit_reveal_weights_interval",
        False,
    ),
    "commit_reveal_weights_enabled": ("sudo_set_commit_reveal_weights_enabled", False),
    "alpha_values": ("sudo_set_alpha_values", False),
    "liquid_alpha_enabled": ("sudo_set_liquid_alpha_enabled", False),
    "registration_allowed": ("sudo_set_network_registration_allowed", False),
    "network_pow_registration_allowed": (
        "sudo_set_network_pow_registration_allowed",
        False,
    ),
}

# Help Panels for cli help
HELP_PANELS = {
    "WALLET": {
        "MANAGEMENT": "Wallet Management",
        "TRANSACTIONS": "Wallet Transactions",
        "IDENTITY": "Identity Management",
        "INFORMATION": "Wallet Information",
        "OPERATIONS": "Wallet Operations",
        "SECURITY": "Security & Recovery",
    },
    "ROOT": {
        "NETWORK": "Network Information",
        "WEIGHT_MGMT": "Weights Management",
        "GOVERNANCE": "Governance",
        "REGISTRATION": "Registration",
        "DELEGATION": "Delegation",
    },
    "STAKE": {
        "STAKE_MGMT": "Stake Management",
        "CHILD": "Child Hotkeys",
        "MOVEMENT": "Stake Movement",
    },
    "SUDO": {
        "CONFIG": "Subnet Configuration",
        "GOVERNANCE": "Governance",
        "TAKE": "Delegate take configuration",
    },
    "SUBNETS": {
        "INFO": "Subnet Information",
        "CREATION": "Subnet Creation & Management",
        "REGISTER": "Neuron Registration",
        "IDENTITY": "Subnet Identity Management",
    },
    "WEIGHTS": {"COMMIT_REVEAL": "Commit / Reveal"},
    "VIEW": {
        "DASHBOARD": "Network Dashboard",
    },
}


class Gettable:
    def __getitem__(self, item):
        return getattr(self, item)


class ColorPalette(Gettable):
    def __init__(self):
        self.GENERAL = self.General()
        self.STAKE = self.Stake()
        self.POOLS = self.Pools()
        self.GREY = self.Grey()
        self.SUDO = self.Sudo()
        # aliases
        self.G = self.GENERAL
        self.S = self.STAKE
        self.P = self.POOLS
        self.GR = self.GREY
        self.SU = self.SUDO

    class General(Gettable):
        HEADER = "#57878B"  # Mid Blue Green
        LINKS = "#8CAAAE"  # Pale Blue
        HINT = "#6C8871"  # Muted Green
        COLDKEY = "#676B72"  # Dark Grey Blue
        HOTKEY = "#747065"  # Dark Orange Grey
        SUBHEADING_MAIN = "#8AA499"  # Muted Blue Green
        SUBHEADING = "#9BAC9C"  # Pale Green
        SUBHEADING_EXTRA_1 = "#C596A3"  # Dusty Rose
        SUBHEADING_EXTRA_2 = "#9BAC9C"  # Pale Green
        CONFIRMATION_Y_N_Q = "#EFB7AB"  # Pale Pink
        SYMBOL = "#FE917A"  # Salmon Orange
        SUBNET_NAME = "#C596A3"  # Dusty Rose
        VALIDATOR_NAME = "#9BAC9C"  # Mid Lime Green
        MINER_NAME = "#A17E7E"  # Dusty Red
        BALANCE = "#757B7B"  # Muted teal Blue
        COST = "#8EB27A"  # Green
        SUCCESS = "#3D7F71"  # Dark Teal
        NETUID = "#BDC1C6"  # GREY_400
        NETUID_EXTRA = "#D4D0C1"  # Light Yellow Grey
        TEMPO = "#927A71"  # Dark Tan Brown
        # aliases
        CK = COLDKEY
        HK = HOTKEY
        SUBHEAD_MAIN = SUBHEADING_MAIN
        SUBHEAD = SUBHEADING
        SUBHEAD_EX_1 = SUBHEADING_EXTRA_1
        SUBHEAD_EX_2 = SUBHEADING_EXTRA_2
        SYM = SYMBOL
        BAL = BALANCE

    class Stake(Gettable):
        STAKE_AMOUNT = "#53B5A0"  # Teal
        STAKE_ALPHA = "#53B5A0"  # Teal
        STAKE_SWAP = "#67A3A5"  # Grayish Teal
        TAO = "#8AA499"  # Faded Blue Green
        SLIPPAGE_TEXT = "#BA938A"  # Brown Salmon
        SLIPPAGE_PERCENT = "#CD8B7B"  # Muted Salmon
        NOT_REGISTERED = "#A87D7D"  # Medium Red brown
        EXTRA_1 = "#A45E44"  # Deep Autumn Orange
        # aliases
        AMOUNT = STAKE_AMOUNT
        ALPHA = STAKE_ALPHA
        SWAP = STAKE_SWAP

    class Pools(Gettable):
        TAO = "#8AA499"  # Faded Blue Green
        ALPHA_IN = "#C1913C"  # Mustard
        ALPHA_OUT = "#B49766"  # Khaki Mustard
        RATE = "#A46844"  # Deep Orange
        TAO_EQUIV = "#93BBAF"  # Teal Blue
        EMISSION = "#B58065"  # Med Orange
        EXTRA_1 = "#919170"  # Autumn green
        EXTRA_2 = "#667862"  # Forest green

    class Grey(Gettable):
        GREY_100 = "#F8F9FA"  # Almost White
        GREY_200 = "#F1F3F4"  # Very Light Grey
        GREY_300 = "#DBDDE1"  # Light Grey
        GREY_400 = "#BDC1C6"  # Medium Light Grey
        GREY_500 = "#5F6368"  # Medium Grey
        GREY_600 = "#2E3134"  # Medium Dark Grey
        GREY_700 = "#282A2D"  # Dark Grey
        GREY_800 = "#17181B"  # Very Dark Grey
        GREY_900 = "#0E1013"  # Almost Black
        BLACK = "#000000"  # Pure Black
        # aliases
        G_100 = GREY_100
        G_200 = GREY_200
        G_300 = GREY_300
        G_400 = GREY_400
        G_500 = GREY_500
        G_600 = GREY_600
        G_700 = GREY_700
        G_800 = GREY_800
        G_900 = GREY_900

    class Sudo(Gettable):
        HYPERPARAMETER = "#93AFA3"  # Forest
        VALUE = "#B58065"  # Burnt Orange
        NORMALIZED = "#A87575"  # Burnt Red
        # aliases
        HYPERPARAM = HYPERPARAMETER
        NORMAL = NORMALIZED


COLOR_PALETTE = ColorPalette()
COLORS = COLOR_PALETTE


SUBNETS = {
    0: "root",
    1: "apex",
    2: "omron",
    3: "templar",
    4: "targon",
    5: "kaito",
    6: "infinite",
    7: "subvortex",
    8: "ptn",
    9: "pretrain",
    10: "sturday",
    11: "dippy",
    12: "horde",
    13: "dataverse",
    14: "palaidn",
    15: "deval",
    16: "bitads",
    17: "3gen",
    18: "cortex",
    19: "inference",
    20: "bitagent",
    21: "any-any",
    22: "meta",
    23: "social",
    24: "omega",
    25: "protein",
    26: "alchemy",
    27: "compute",
    28: "oracle",
    29: "coldint",
    30: "bet",
    31: "naschain",
    32: "itsai",
    33: "ready",
    34: "mind",
    35: "logic",
    36: "automata",
    37: "tuning",
    38: "distributed",
    39: "edge",
    40: "chunk",
    41: "sportsensor",
    42: "masa",
    43: "graphite",
    44: "score",
    45: "gen42",
    46: "neural",
    47: "condense",
    48: "nextplace",
    49: "automl",
    50: "audio",
    51: "celium",
    52: "dojo",
    53: "frontier",
    54: "docs-insight",
    56: "gradients",
    57: "gaia",
    58: "dippy-speech",
    59: "agent-arena",
    61: "red-team",
}
