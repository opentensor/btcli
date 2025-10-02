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
    lite_nodes = [finney_entrypoint, subvortex_entrypoint, latent_lite_entrypoint]
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
        debug_file_path = "~/.bittensor/debug.txt"
        dictionary = {
            "network": None,
            "wallet_path": None,
            "wallet_name": None,
            "wallet_hotkey": None,
            "use_cache": True,
            "disk_cache": False,
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
    b"\xce\xa4".decode(),  # Τ (Upper case Tau, 0)
    b"\xce\xb1".decode(),  # α (Alpha, 1)
    b"\xce\xb2".decode(),  # β (Beta, 2)
    b"\xce\xb3".decode(),  # γ (Gamma, 3)
    b"\xce\xb4".decode(),  # δ (Delta, 4)
    b"\xce\xb5".decode(),  # ε (Epsilon, 5)
    b"\xce\xb6".decode(),  # ζ (Zeta, 6)
    b"\xce\xb7".decode(),  # η (Eta, 7)
    b"\xce\xb8".decode(),  # θ (Theta, 8)
    b"\xce\xb9".decode(),  # ι (Iota, 9)
    b"\xce\xba".decode(),  # κ (Kappa, 10)
    b"\xce\xbb".decode(),  # λ (Lambda, 11)
    b"\xce\xbc".decode(),  # μ (Mu, 12)
    b"\xce\xbd".decode(),  # ν (Nu, 13)
    b"\xce\xbe".decode(),  # ξ (Xi, 14)
    b"\xce\xbf".decode(),  # ο (Omicron, 15)
    b"\xcf\x80".decode(),  # π (Pi, 16)
    b"\xcf\x81".decode(),  # ρ (Rho, 17)
    b"\xcf\x83".decode(),  # σ (Sigma, 18)
    "t",  # t (Tau, 19)
    b"\xcf\x85".decode(),  # υ (Upsilon, 20)
    b"\xcf\x86".decode(),  # φ (Phi, 21)
    b"\xcf\x87".decode(),  # χ (Chi, 22)
    b"\xcf\x88".decode(),  # ψ (Psi, 23)
    b"\xcf\x89".decode(),  # ω (Omega, 24)
    b"\xd7\x90".decode(),  # א (Aleph, 25)
    b"\xd7\x91".decode(),  # ב (Bet, 26)
    b"\xd7\x92".decode(),  # ג (Gimel, 27)
    b"\xd7\x93".decode(),  # ד (Dalet, 28)
    b"\xd7\x94".decode(),  # ה (He, 29)
    b"\xd7\x95".decode(),  # ו (Vav, 30)
    b"\xd7\x96".decode(),  # ז (Zayin, 31)
    b"\xd7\x97".decode(),  # ח (Het, 32)
    b"\xd7\x98".decode(),  # ט (Tet, 33)
    b"\xd7\x99".decode(),  # י (Yod, 34)
    b"\xd7\x9a".decode(),  # ך (Final Kaf, 35)
    b"\xd7\x9b".decode(),  # כ (Kaf, 36)
    b"\xd7\x9c".decode(),  # ל (Lamed, 37)
    b"\xd7\x9d".decode(),  # ם (Final Mem, 38)
    b"\xd7\x9e".decode(),  # מ (Mem, 39)
    b"\xd7\x9f".decode(),  # ן (Final Nun, 40)
    b"\xd7\xa0".decode(),  # נ (Nun, 41)
    b"\xd7\xa1".decode(),  # ס (Samekh, 42)
    b"\xd7\xa2".decode(),  # ע (Ayin, 43)
    b"\xd7\xa3".decode(),  # ף (Final Pe, 44)
    b"\xd7\xa4".decode(),  # פ (Pe, 45)
    b"\xd7\xa5".decode(),  # ץ (Final Tsadi, 46)
    b"\xd7\xa6".decode(),  # צ (Tsadi, 47)
    b"\xd7\xa7".decode(),  # ק (Qof, 48)
    b"\xd7\xa8".decode(),  # ר (Resh, 49)
    b"\xd7\xa9".decode(),  # ש (Shin, 50)
    b"\xd7\xaa".decode(),  # ת (Tav, 51)
    b"\xd8\xa7".decode(),  # ا (Alif, 52)
    b"\xd8\xa8".decode(),  # ب (Ba, 53)
    b"\xd8\xaa".decode(),  # ت (Ta, 54)
    b"\xd8\xab".decode(),  # ث (Tha, 55)
    b"\xd8\xac".decode(),  # ج (Jim, 56)
    b"\xd8\xad".decode(),  # ح (Ha, 57)
    b"\xd8\xae".decode(),  # خ (Kha, 58)
    b"\xd8\xaf".decode(),  # د (Dal, 59)
    b"\xd8\xb0".decode(),  # ذ (Dhal, 60)
    b"\xd8\xb1".decode(),  # ر (Ra, 61)
    b"\xd8\xb2".decode(),  # ز (Zay, 62)
    b"\xd8\xb3".decode(),  # س (Sin, 63)
    b"\xd8\xb4".decode(),  # ش (Shin, 64)
    b"\xd8\xb5".decode(),  # ص (Sad, 65)
    b"\xd8\xb6".decode(),  # ض (Dad, 66)
    b"\xd8\xb7".decode(),  # ط (Ta, 67)
    b"\xd8\xb8".decode(),  # ظ (Dha, 68)
    b"\xd8\xb9".decode(),  # ع (Ain, 69)
    b"\xd8\xba".decode(),  # غ (Ghayn, 70)
    b"\xd9\x81".decode(),  # ف (Fa, 71)
    b"\xd9\x82".decode(),  # ق (Qaf, 72)
    b"\xd9\x83".decode(),  # ك (Kaf, 73)
    b"\xd9\x84".decode(),  # ل (Lam, 74)
    b"\xd9\x85".decode(),  # م (Mim, 75)
    b"\xd9\x86".decode(),  # ن (Nun, 76)
    b"\xd9\x87".decode(),  # ه (Ha, 77)
    b"\xd9\x88".decode(),  # و (Waw, 78)
    b"\xd9\x8a".decode(),  # ي (Ya, 79)
    b"\xd9\x89".decode(),  # ى (Alef Maksura, 80)
    b"\xe1\x9a\xa0".decode(),  # ᚠ (Fehu, wealth, 81)
    b"\xe1\x9a\xa2".decode(),  # ᚢ (Uruz, strength, 82)
    b"\xe1\x9a\xa6".decode(),  # ᚦ (Thurisaz, giant, 83)
    b"\xe1\x9a\xa8".decode(),  # ᚨ (Ansuz, god, 84)
    b"\xe1\x9a\xb1".decode(),  # ᚱ (Raidho, ride, 85)
    b"\xe1\x9a\xb3".decode(),  # ᚲ (Kaunan, ulcer, 86)
    b"\xd0\xab".decode(),  # Ы (Cyrillic Yeru, 87)
    b"\xe1\x9b\x89".decode(),  # ᛉ (Algiz, protection, 88)
    b"\xe1\x9b\x92".decode(),  # ᛒ (Berkanan, birch, 89)
    b"\xe1\x9a\x80".decode(),  #   (Space, 90)
    b"\xe1\x9a\x81".decode(),  # ᚁ (Beith, birch, 91)
    b"\xe1\x9a\x82".decode(),  # ᚂ (Luis, rowan, 92)
    b"\xe1\x9a\x83".decode(),  # ᚃ (Fearn, alder, 93)
    b"\xe1\x9a\x84".decode(),  # ᚄ (Sail, willow, 94)
    b"\xe1\x9a\x85".decode(),  # ᚅ (Nion, ash, 95)
    b"\xe1\x9a\x9b".decode(),  # ᚛ (Forfeda, 96)
    b"\xe1\x83\x90".decode(),  # ა (Ani, 97)
    b"\xe1\x83\x91".decode(),  # ბ (Bani, 98)
    b"\xe1\x83\x92".decode(),  # გ (Gani, 99)
    b"\xe1\x83\x93".decode(),  # დ (Doni, 100)
    b"\xe1\x83\x94".decode(),  # ე (Eni, 101)
    b"\xe1\x83\x95".decode(),  # ვ (Vini, 102)
    b"\xd4\xb1".decode(),  # Ա (Ayp, 103)
    b"\xd4\xb2".decode(),  # Բ (Ben, 104)
    b"\xd4\xb3".decode(),  # Գ (Gim, 105)
    b"\xd4\xb4".decode(),  # Դ (Da, 106)
    b"\xd4\xb5".decode(),  # Ե (Ech, 107)
    b"\xd4\xb6".decode(),  # Զ (Za, 108)
    b"\xd5\x9e".decode(),  # ՞ (Question mark, 109)
    b"\xd0\x80".decode(),  # Ѐ (Ie with grave, 110)
    b"\xd0\x81".decode(),  # Ё (Io, 111)
    b"\xd0\x82".decode(),  # Ђ (Dje, 112)
    b"\xd0\x83".decode(),  # Ѓ (Gje, 113)
    b"\xd0\x84".decode(),  # Є (Ukrainian Ie, 114)
    b"\xd0\x85".decode(),  # Ѕ (Dze, 115)
    b"\xd1\x8a".decode(),  # Ъ (Hard sign, 116)
    b"\xe2\xb2\x80".decode(),  # Ⲁ (Alfa, 117)
    b"\xe2\xb2\x81".decode(),  # ⲁ (Small Alfa, 118)
    b"\xe2\xb2\x82".decode(),  # Ⲃ (Vida, 119)
    b"\xe2\xb2\x83".decode(),  # ⲃ (Small Vida, 120)
    b"\xe2\xb2\x84".decode(),  # Ⲅ (Gamma, 121)
    b"\xe2\xb2\x85".decode(),  # ⲅ (Small Gamma, 122)
    b"\xf0\x91\x80\x80".decode(),  # 𑀀 (A, 123)
    b"\xf0\x91\x80\x81".decode(),  # 𑀁 (Aa, 124)
    b"\xf0\x91\x80\x82".decode(),  # 𑀂 (I, 125)
    b"\xf0\x91\x80\x83".decode(),  # 𑀃 (Ii, 126)
    b"\xf0\x91\x80\x85".decode(),  # 𑀅 (U, 127)
    b"\xe0\xb6\xb1".decode(),  # ඲ (La, 128)
    b"\xe0\xb6\xb2".decode(),  # ඳ (Va, 129)
    b"\xe0\xb6\xb3".decode(),  # ප (Sha, 130)
    b"\xe0\xb6\xb4".decode(),  # ඵ (Ssa, 131)
    b"\xe0\xb6\xb5".decode(),  # බ (Sa, 132)
    b"\xe0\xb6\xb6".decode(),  # භ (Ha, 133)
    b"\xe2\xb0\x80".decode(),  # Ⰰ (Az, 134)
    b"\xe2\xb0\x81".decode(),  # Ⰱ (Buky, 135)
    b"\xe2\xb0\x82".decode(),  # Ⰲ (Vede, 136)
    b"\xe2\xb0\x83".decode(),  # Ⰳ (Glagoli, 137)
    b"\xe2\xb0\x84".decode(),  # Ⰴ (Dobro, 138)
    b"\xe2\xb0\x85".decode(),  # Ⰵ (Yest, 139)
    b"\xe2\xb0\x86".decode(),  # Ⰶ (Zhivete, 140)
    b"\xe2\xb0\x87".decode(),  # Ⰷ (Zemlja, 141)
    b"\xe2\xb0\x88".decode(),  # Ⰸ (Izhe, 142)
    b"\xe2\xb0\x89".decode(),  # Ⰹ (Initial Izhe, 143)
    b"\xe2\xb0\x8a".decode(),  # Ⰺ (I, 144)
    b"\xe2\xb0\x8b".decode(),  # Ⰻ (Djerv, 145)
    b"\xe2\xb0\x8c".decode(),  # Ⰼ (Kako, 146)
    b"\xe2\xb0\x8d".decode(),  # Ⰽ (Ljudije, 147)
    b"\xe2\xb0\x8e".decode(),  # Ⰾ (Myse, 148)
    b"\xe2\xb0\x8f".decode(),  # Ⰿ (Nash, 149)
    b"\xe2\xb0\x90".decode(),  # Ⱀ (On, 150)
    b"\xe2\xb0\x91".decode(),  # Ⱁ (Pokoj, 151)
    b"\xe2\xb0\x92".decode(),  # Ⱂ (Rtsy, 152)
    b"\xe2\xb0\x93".decode(),  # Ⱃ (Slovo, 153)
    b"\xe2\xb0\x94".decode(),  # Ⱄ (Tvrido, 154)
    b"\xe2\xb0\x95".decode(),  # Ⱅ (Uku, 155)
    b"\xe2\xb0\x96".decode(),  # Ⱆ (Fert, 156)
    b"\xe2\xb0\x97".decode(),  # Ⱇ (Xrivi, 157)
    b"\xe2\xb0\x98".decode(),  # Ⱈ (Ot, 158)
    b"\xe2\xb0\x99".decode(),  # Ⱉ (Cy, 159)
    b"\xe2\xb0\x9a".decode(),  # Ⱊ (Shcha, 160)
    b"\xe2\xb0\x9b".decode(),  # Ⱋ (Er, 161)
    b"\xe2\xb0\x9c".decode(),  # Ⱌ (Yeru, 162)
    b"\xe2\xb0\x9d".decode(),  # Ⱍ (Small Yer, 163)
    b"\xe2\xb0\x9e".decode(),  # Ⱎ (Yo, 164)
    b"\xe2\xb0\x9f".decode(),  # Ⱏ (Yu, 165)
    b"\xe2\xb0\xa0".decode(),  # Ⱐ (Ja, 166)
    b"\xe0\xb8\x81".decode(),  # ก (Ko Kai, 167)
    b"\xe0\xb8\x82".decode(),  # ข (Kho Khai, 168)
    b"\xe0\xb8\x83".decode(),  # ฃ (Kho Khuat, 169)
    b"\xe0\xb8\x84".decode(),  # ค (Kho Khon, 170)
    b"\xe0\xb8\x85".decode(),  # ฅ (Kho Rakhang, 171)
    b"\xe0\xb8\x86".decode(),  # ฆ (Kho Khwai, 172)
    b"\xe0\xb8\x87".decode(),  # ง (Ngo Ngu, 173)
    b"\xe0\xb8\x88".decode(),  # จ (Cho Chan, 174)
    b"\xe0\xb8\x89".decode(),  # ฉ (Cho Ching, 175)
    b"\xe0\xb8\x8a".decode(),  # ช (Cho Chang, 176)
    b"\xe0\xb8\x8b".decode(),  # ซ (So So, 177)
    b"\xe0\xb8\x8c".decode(),  # ฌ (Cho Choe, 178)
    b"\xe0\xb8\x8d".decode(),  # ญ (Yo Ying, 179)
    b"\xe0\xb8\x8e".decode(),  # ฎ (Do Chada, 180)
    b"\xe0\xb8\x8f".decode(),  # ฏ (To Patak, 181)
    b"\xe0\xb8\x90".decode(),  # ฐ (Tho Than, 182)
    b"\xe0\xb8\x91".decode(),  # ฑ (Tho Nangmontho, 183)
    b"\xe0\xb8\x92".decode(),  # ฒ (Tho Phuthao, 184)
    b"\xe0\xb8\x93".decode(),  # ณ (No Nen, 185)
    b"\xe0\xb8\x94".decode(),  # ด (Do Dek, 186)
    b"\xe0\xb8\x95".decode(),  # ต (To Tao, 187)
    b"\xe0\xb8\x96".decode(),  # ถ (Tho Thung, 188)
    b"\xe0\xb8\x97".decode(),  # ท (Tho Thahan, 189)
    b"\xe0\xb8\x98".decode(),  # ธ (Tho Thong, 190)
    b"\xe0\xb8\x99".decode(),  # น (No Nu, 191)
    b"\xe0\xb8\x9a".decode(),  # บ (Bo Baimai, 192)
    b"\xe0\xb8\x9b".decode(),  # ป (Po Pla, 193)
    b"\xe0\xb8\x9c".decode(),  # ผ (Pho Phung, 194)
    b"\xe0\xb8\x9d".decode(),  # ฝ (Fo Fa, 195)
    b"\xe0\xb8\x9e".decode(),  # พ (Pho Phan, 196)
    b"\xe0\xb8\x9f".decode(),  # ฟ (Fo Fan, 197)
    b"\xe0\xb8\xa0".decode(),  # ภ (Pho Samphao, 198)
    b"\xe0\xb8\xa1".decode(),  # ม (Mo Ma, 199)
    b"\xe0\xb8\xa2".decode(),  # ย (Yo Yak, 200)
    b"\xe0\xb8\xa3".decode(),  # ร (Ro Rua, 201)
    b"\xe0\xb8\xa5".decode(),  # ล (Lo Ling, 202)
    b"\xe0\xb8\xa7".decode(),  # ว (Wo Waen, 203)
    b"\xe0\xb8\xa8".decode(),  # ศ (So Sala, 204)
    b"\xe0\xb8\xa9".decode(),  # ษ (So Rusi, 205)
    b"\xe0\xb8\xaa".decode(),  # ส (So Sua, 206)
    b"\xe0\xb8\xab".decode(),  # ห (Ho Hip, 207)
    b"\xe0\xb8\xac".decode(),  # ฬ (Lo Chula, 208)
    b"\xe0\xb8\xad".decode(),  # อ (O Ang, 209)
    b"\xe0\xb8\xae".decode(),  # ฮ (Ho Nokhuk, 210)
    b"\xe1\x84\x80".decode(),  # ㄱ (Giyeok, 211)
    b"\xe1\x84\x81".decode(),  # ㄴ (Nieun, 212)
    b"\xe1\x84\x82".decode(),  # ㄷ (Digeut, 213)
    b"\xe1\x84\x83".decode(),  # ㄹ (Rieul, 214)
    b"\xe1\x84\x84".decode(),  # ㅁ (Mieum, 215)
    b"\xe1\x84\x85".decode(),  # ㅂ (Bieup, 216)
    b"\xe1\x84\x86".decode(),  # ㅅ (Siot, 217)
    b"\xe1\x84\x87".decode(),  # ㅇ (Ieung, 218)
    b"\xe1\x84\x88".decode(),  # ㅈ (Jieut, 219)
    b"\xe1\x84\x89".decode(),  # ㅊ (Chieut, 220)
    b"\xe1\x84\x8a".decode(),  # ㅋ (Kieuk, 221)
    b"\xe1\x84\x8b".decode(),  # ㅌ (Tieut, 222)
    b"\xe1\x84\x8c".decode(),  # ㅍ (Pieup, 223)
    b"\xe1\x84\x8d".decode(),  # ㅎ (Hieut, 224)
    b"\xe1\x85\xa1".decode(),  # ㅏ (A, 225)
    b"\xe1\x85\xa2".decode(),  # ㅐ (Ae, 226)
    b"\xe1\x85\xa3".decode(),  # ㅑ (Ya, 227)
    b"\xe1\x85\xa4".decode(),  # ㅒ (Yae, 228)
    b"\xe1\x85\xa5".decode(),  # ㅓ (Eo, 229)
    b"\xe1\x85\xa6".decode(),  # ㅔ (E, 230)
    b"\xe1\x85\xa7".decode(),  # ㅕ (Yeo, 231)
    b"\xe1\x85\xa8".decode(),  # ㅖ (Ye, 232)
    b"\xe1\x85\xa9".decode(),  # ㅗ (O, 233)
    b"\xe1\x85\xaa".decode(),  # ㅘ (Wa, 234)
    b"\xe1\x85\xab".decode(),  # ㅙ (Wae, 235)
    b"\xe1\x85\xac".decode(),  # ㅚ (Oe, 236)
    b"\xe1\x85\xad".decode(),  # ㅛ (Yo, 237)
    b"\xe1\x85\xae".decode(),  # ㅜ (U, 238)
    b"\xe1\x85\xaf".decode(),  # ㅝ (Weo, 239)
    b"\xe1\x85\xb0".decode(),  # ㅞ (We, 240)
    b"\xe1\x85\xb1".decode(),  # ㅟ (Wi, 241)
    b"\xe1\x85\xb2".decode(),  # ㅠ (Yu, 242)
    b"\xe1\x85\xb3".decode(),  # ㅡ (Eu, 243)
    b"\xe1\x85\xb4".decode(),  # ㅢ (Ui, 244)
    b"\xe1\x85\xb5".decode(),  # ㅣ (I, 245)
    b"\xe1\x8a\xa0".decode(),  # አ (Glottal A, 246)
    b"\xe1\x8a\xa1".decode(),  # ኡ (Glottal U, 247)
    b"\xe1\x8a\xa2".decode(),  # ኢ (Glottal I, 248)
    b"\xe1\x8a\xa3".decode(),  # ኣ (Glottal Aa, 249)
    b"\xe1\x8a\xa4".decode(),  # ኤ (Glottal E, 250)
    b"\xe1\x8a\xa5".decode(),  # እ (Glottal Ie, 251)
    b"\xe1\x8a\xa6".decode(),  # ኦ (Glottal O, 252)
    b"\xe1\x8a\xa7".decode(),  # ኧ (Glottal Wa, 253)
    b"\xe1\x8b\x88".decode(),  # ወ (Wa, 254)
    b"\xe1\x8b\x89".decode(),  # ዉ (Wu, 255)
    b"\xe1\x8b\x8a".decode(),  # ዊ (Wi, 256)
    b"\xe1\x8b\x8b".decode(),  # ዋ (Waa, 257)
    b"\xe1\x8b\x8c".decode(),  # ዌ (We, 258)
    b"\xe1\x8b\x8d".decode(),  # ው (Wye, 259)
    b"\xe1\x8b\x8e".decode(),  # ዎ (Wo, 260)
    b"\xe1\x8a\xb0".decode(),  # ኰ (Ko, 261)
    b"\xe1\x8a\xb1".decode(),  # ኱ (Ku, 262)
    b"\xe1\x8a\xb2".decode(),  # ኲ (Ki, 263)
    b"\xe1\x8a\xb3".decode(),  # ኳ (Kua, 264)
    b"\xe1\x8a\xb4".decode(),  # ኴ (Ke, 265)
    b"\xe1\x8a\xb5".decode(),  # ኵ (Kwe, 266)
    b"\xe1\x8a\xb6".decode(),  # ኶ (Ko, 267)
    b"\xe1\x8a\x90".decode(),  # ጐ (Go, 268)
    b"\xe1\x8a\x91".decode(),  # ጑ (Gu, 269)
    b"\xe1\x8a\x92".decode(),  # ጒ (Gi, 270)
    b"\xe1\x8a\x93".decode(),  # መ (Gua, 271)
    b"\xe1\x8a\x94".decode(),  # ጔ (Ge, 272)
    b"\xe1\x8a\x95".decode(),  # ጕ (Gwe, 273)
    b"\xe1\x8a\x96".decode(),  # ጖ (Go, 274)
    b"\xe0\xa4\x85".decode(),  # अ (A, 275)
    b"\xe0\xa4\x86".decode(),  # आ (Aa, 276)
    b"\xe0\xa4\x87".decode(),  # इ (I, 277)
    b"\xe0\xa4\x88".decode(),  # ई (Ii, 278)
    b"\xe0\xa4\x89".decode(),  # उ (U, 279)
    b"\xe0\xa4\x8a".decode(),  # ऊ (Uu, 280)
    b"\xe0\xa4\x8b".decode(),  # ऋ (R, 281)
    b"\xe0\xa4\x8f".decode(),  # ए (E, 282)
    b"\xe0\xa4\x90".decode(),  # ऐ (Ai, 283)
    b"\xe0\xa4\x93".decode(),  # ओ (O, 284)
    b"\xe0\xa4\x94".decode(),  # औ (Au, 285)
    b"\xe0\xa4\x95".decode(),  # क (Ka, 286)
    b"\xe0\xa4\x96".decode(),  # ख (Kha, 287)
    b"\xe0\xa4\x97".decode(),  # ग (Ga, 288)
    b"\xe0\xa4\x98".decode(),  # घ (Gha, 289)
    b"\xe0\xa4\x99".decode(),  # ङ (Nga, 290)
    b"\xe0\xa4\x9a".decode(),  # च (Cha, 291)
    b"\xe0\xa4\x9b".decode(),  # छ (Chha, 292)
    b"\xe0\xa4\x9c".decode(),  # ज (Ja, 293)
    b"\xe0\xa4\x9d".decode(),  # झ (Jha, 294)
    b"\xe0\xa4\x9e".decode(),  # ञ (Nya, 295)
    b"\xe0\xa4\x9f".decode(),  # ट (Ta, 296)
    b"\xe0\xa4\xa0".decode(),  # ठ (Tha, 297)
    b"\xe0\xa4\xa1".decode(),  # ड (Da, 298)
    b"\xe0\xa4\xa2".decode(),  # ढ (Dha, 299)
    b"\xe0\xa4\xa3".decode(),  # ण (Na, 300)
    b"\xe0\xa4\xa4".decode(),  # त (Ta, 301)
    b"\xe0\xa4\xa5".decode(),  # थ (Tha, 302)
    b"\xe0\xa4\xa6".decode(),  # द (Da, 303)
    b"\xe0\xa4\xa7".decode(),  # ध (Dha, 304)
    b"\xe0\xa4\xa8".decode(),  # न (Na, 305)
    b"\xe0\xa4\xaa".decode(),  # प (Pa, 306)
    b"\xe0\xa4\xab".decode(),  # फ (Pha, 307)
    b"\xe0\xa4\xac".decode(),  # ब (Ba, 308)
    b"\xe0\xa4\xad".decode(),  # भ (Bha, 309)
    b"\xe0\xa4\xae".decode(),  # म (Ma, 310)
    b"\xe0\xa4\xaf".decode(),  # य (Ya, 311)
    b"\xe0\xa4\xb0".decode(),  # र (Ra, 312)
    b"\xe0\xa4\xb2".decode(),  # ल (La, 313)
    b"\xe0\xa4\xb5".decode(),  # व (Va, 314)
    b"\xe0\xa4\xb6".decode(),  # श (Sha, 315)
    b"\xe0\xa4\xb7".decode(),  # ष (Ssa, 316)
    b"\xe0\xa4\xb8".decode(),  # स (Sa, 317)
    b"\xe0\xa4\xb9".decode(),  # ह (Ha, 318)
    b"\xe3\x82\xa2".decode(),  # ア (A, 319)
    b"\xe3\x82\xa4".decode(),  # イ (I, 320)
    b"\xe3\x82\xa6".decode(),  # ウ (U, 321)
    b"\xe3\x82\xa8".decode(),  # エ (E, 322)
    b"\xe3\x82\xaa".decode(),  # オ (O, 323)
    b"\xe3\x82\xab".decode(),  # カ (Ka, 324)
    b"\xe3\x82\xad".decode(),  # キ (Ki, 325)
    b"\xe3\x82\xaf".decode(),  # ク (Ku, 326)
    b"\xe3\x82\xb1".decode(),  # ケ (Ke, 327)
    b"\xe3\x82\xb3".decode(),  # コ (Ko, 328)
    b"\xe3\x82\xb5".decode(),  # サ (Sa, 329)
    b"\xe3\x82\xb7".decode(),  # シ (Shi, 330)
    b"\xe3\x82\xb9".decode(),  # ス (Su, 331)
    b"\xe3\x82\xbb".decode(),  # セ (Se, 332)
    b"\xe3\x82\xbd".decode(),  # ソ (So, 333)
    b"\xe3\x82\xbf".decode(),  # タ (Ta, 334)
    b"\xe3\x83\x81".decode(),  # チ (Chi, 335)
    b"\xe3\x83\x84".decode(),  # ツ (Tsu, 336)
    b"\xe3\x83\x86".decode(),  # テ (Te, 337)
    b"\xe3\x83\x88".decode(),  # ト (To, 338)
    b"\xe3\x83\x8a".decode(),  # ナ (Na, 339)
    b"\xe3\x83\x8b".decode(),  # ニ (Ni, 340)
    b"\xe3\x83\x8c".decode(),  # ヌ (Nu, 341)
    b"\xe3\x83\x8d".decode(),  # ネ (Ne, 342)
    b"\xe3\x83\x8e".decode(),  # ノ (No, 343)
    b"\xe3\x83\x8f".decode(),  # ハ (Ha, 344)
    b"\xe3\x83\x92".decode(),  # ヒ (Hi, 345)
    b"\xe3\x83\x95".decode(),  # フ (Fu, 346)
    b"\xe3\x83\x98".decode(),  # ヘ (He, 347)
    b"\xe3\x83\x9b".decode(),  # ホ (Ho, 348)
    b"\xe3\x83\x9e".decode(),  # マ (Ma, 349)
    b"\xe3\x83\x9f".decode(),  # ミ (Mi, 350)
    b"\xe3\x83\xa0".decode(),  # ム (Mu, 351)
    b"\xe3\x83\xa1".decode(),  # メ (Me, 352)
    b"\xe3\x83\xa2".decode(),  # モ (Mo, 353)
    b"\xe3\x83\xa4".decode(),  # ヤ (Ya, 354)
    b"\xe3\x83\xa6".decode(),  # ユ (Yu, 355)
    b"\xe3\x83\xa8".decode(),  # ヨ (Yo, 356)
    b"\xe3\x83\xa9".decode(),  # ラ (Ra, 357)
    b"\xe3\x83\xaa".decode(),  # リ (Ri, 358)
    b"\xe3\x83\xab".decode(),  # ル (Ru, 359)
    b"\xe3\x83\xac".decode(),  # レ (Re, 360)
    b"\xe3\x83\xad".decode(),  # ロ (Ro, 361)
    b"\xe3\x83\xaf".decode(),  # ワ (Wa, 362)
    b"\xe3\x83\xb2".decode(),  # ヲ (Wo, 363)
    b"\xe3\x83\xb3".decode(),  # ン (N, 364)
    b"\xe2\xb4\xb0".decode(),  # ⴰ (Ya, 365)
    b"\xe2\xb4\xb1".decode(),  # ⴱ (Yab, 366)
    b"\xe2\xb4\xb2".decode(),  # ⴲ (Yabh, 367)
    b"\xe2\xb4\xb3".decode(),  # ⴳ (Yag, 368)
    b"\xe2\xb4\xb4".decode(),  # ⴴ (Yagh, 369)
    b"\xe2\xb4\xb5".decode(),  # ⴵ (Yaj, 370)
    b"\xe2\xb4\xb6".decode(),  # ⴶ (Yach, 371)
    b"\xe2\xb4\xb7".decode(),  # ⴷ (Yad, 372)
    b"\xe2\xb4\xb8".decode(),  # ⴸ (Yadh, 373)
    b"\xe2\xb4\xb9".decode(),  # ⴹ (Yadh, emphatic, 374)
    b"\xe2\xb4\xba".decode(),  # ⴺ (Yaz, 375)
    b"\xe2\xb4\xbb".decode(),  # ⴻ (Yazh, 376)
    b"\xe2\xb4\xbc".decode(),  # ⴼ (Yaf, 377)
    b"\xe2\xb4\xbd".decode(),  # ⴽ (Yak, 378)
    b"\xe2\xb4\xbe".decode(),  # ⴾ (Yak, variant, 379)
    b"\xe2\xb4\xbf".decode(),  # ⴿ (Yaq, 380)
    b"\xe2\xb5\x80".decode(),  # ⵀ (Yah, 381)
    b"\xe2\xb5\x81".decode(),  # ⵁ (Yahh, 382)
    b"\xe2\xb5\x82".decode(),  # ⵂ (Yahl, 383)
    b"\xe2\xb5\x83".decode(),  # ⵃ (Yahm, 384)
    b"\xe2\xb5\x84".decode(),  # ⵄ (Yayn, 385)
    b"\xe2\xb5\x85".decode(),  # ⵅ (Yakh, 386)
    b"\xe2\xb5\x86".decode(),  # ⵆ (Yakl, 387)
    b"\xe2\xb5\x87".decode(),  # ⵇ (Yahq, 388)
    b"\xe2\xb5\x88".decode(),  # ⵈ (Yash, 389)
    b"\xe2\xb5\x89".decode(),  # ⵉ (Yi, 390)
    b"\xe2\xb5\x8a".decode(),  # ⵊ (Yij, 391)
    b"\xe2\xb5\x8b".decode(),  # ⵋ (Yizh, 392)
    b"\xe2\xb5\x8c".decode(),  # ⵌ (Yink, 393)
    b"\xe2\xb5\x8d".decode(),  # ⵍ (Yal, 394)
    b"\xe2\xb5\x8e".decode(),  # ⵎ (Yam, 395)
    b"\xe2\xb5\x8f".decode(),  # ⵏ (Yan, 396)
    b"\xe2\xb5\x90".decode(),  # ⵐ (Yang, 397)
    b"\xe2\xb5\x91".decode(),  # ⵑ (Yany, 398)
    b"\xe2\xb5\x92".decode(),  # ⵒ (Yap, 399)
    b"\xe2\xb5\x93".decode(),  # ⵓ (Yu, 400)
    b"\xe0\xb6\x85".decode(),  # අ (A, 401)
    b"\xe0\xb6\x86".decode(),  # ආ (Aa, 402)
    b"\xe0\xb6\x87".decode(),  # ඉ (I, 403)
    b"\xe0\xb6\x88".decode(),  # ඊ (Ii, 404)
    b"\xe0\xb6\x89".decode(),  # උ (U, 405)
    b"\xe0\xb6\x8a".decode(),  # ඌ (Uu, 406)
    b"\xe0\xb6\x8b".decode(),  # ඍ (R, 407)
    b"\xe0\xb6\x8c".decode(),  # ඎ (Rr, 408)
    b"\xe0\xb6\x8f".decode(),  # ඏ (L, 409)
    b"\xe0\xb6\x90".decode(),  # ඐ (Ll, 410)
    b"\xe0\xb6\x91".decode(),  # එ (E, 411)
    b"\xe0\xb6\x92".decode(),  # ඒ (Ee, 412)
    b"\xe0\xb6\x93".decode(),  # ඓ (Ai, 413)
    b"\xe0\xb6\x94".decode(),  # ඔ (O, 414)
    b"\xe0\xb6\x95".decode(),  # ඕ (Oo, 415)
    b"\xe0\xb6\x96".decode(),  # ඖ (Au, 416)
    b"\xe0\xb6\x9a".decode(),  # ක (Ka, 417)
    b"\xe0\xb6\x9b".decode(),  # ඛ (Kha, 418)
    b"\xe0\xb6\x9c".decode(),  # ග (Ga, 419)
    b"\xe0\xb6\x9d".decode(),  # ඝ (Gha, 420)
    b"\xe0\xb6\x9e".decode(),  # ඞ (Nga, 421)
    b"\xe0\xb6\x9f".decode(),  # ච (Cha, 422)
    b"\xe0\xb6\xa0".decode(),  # ඡ (Chha, 423)
    b"\xe0\xb6\xa1".decode(),  # ජ (Ja, 424)
    b"\xe0\xb6\xa2".decode(),  # ඣ (Jha, 425)
    b"\xe0\xb6\xa3".decode(),  # ඤ (Nya, 426)
    b"\xe0\xb6\xa4".decode(),  # ට (Ta, 427)
    b"\xe0\xb6\xa5".decode(),  # ඥ (Tha, 428)
    b"\xe0\xb6\xa6".decode(),  # ඦ (Da, 429)
    b"\xe0\xb6\xa7".decode(),  # ට (Dha, 430)
    b"\xe0\xb6\xa8".decode(),  # ඨ (Na, 431)
    b"\xe0\xb6\xaa".decode(),  # ඪ (Pa, 432)
    b"\xe0\xb6\xab".decode(),  # ණ (Pha, 433)
    b"\xe0\xb6\xac".decode(),  # ඬ (Ba, 434)
    b"\xe0\xb6\xad".decode(),  # ත (Bha, 435)
    b"\xe0\xb6\xae".decode(),  # ථ (Ma, 436)
    b"\xe0\xb6\xaf".decode(),  # ද (Ya, 437)
    b"\xe0\xb6\xb0".decode(),  # ධ (Ra, 438)
]

NETWORK_EXPLORER_MAP = {
    "opentensor": {
        "local": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "endpoint": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
        "finney": "https://polkadot.js.org/apps/?rpc=wss%3A%2F%2Fentrypoint-finney.opentensor.ai%3A443#/explorer",
    },
    "taostats": {
        "local": "https://taostats.io",
        "endpoint": "https://taostats.io",
        "finney": "https://taostats.io",
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
    "min_difficulty": ("sudo_set_min_difficulty", True),
    "max_difficulty": ("sudo_set_max_difficulty", False),
    "weights_version": ("sudo_set_weights_version_key", False),
    "weights_rate_limit": ("sudo_set_weights_set_rate_limit", True),
    "adjustment_interval": ("sudo_set_adjustment_interval", True),
    "activity_cutoff": ("sudo_set_activity_cutoff", False),
    "target_regs_per_interval": ("sudo_set_target_registrations_per_interval", True),
    "min_burn": ("sudo_set_min_burn", False),
    "max_burn": ("sudo_set_max_burn", True),
    "bonds_moving_avg": ("sudo_set_bonds_moving_average", False),
    "max_regs_per_block": ("sudo_set_max_registrations_per_block", True),
    "serving_rate_limit": ("sudo_set_serving_rate_limit", False),
    "max_validators": ("sudo_set_max_allowed_validators", True),
    "adjustment_alpha": ("sudo_set_adjustment_alpha", False),
    "difficulty": ("sudo_set_difficulty", True),
    "commit_reveal_period": (
        "sudo_set_commit_reveal_weights_interval",
        False,
    ),
    "commit_reveal_weights_enabled": ("sudo_set_commit_reveal_weights_enabled", False),
    "alpha_values": ("sudo_set_alpha_values", False),
    "liquid_alpha_enabled": ("sudo_set_liquid_alpha_enabled", False),
    "registration_allowed": ("sudo_set_network_registration_allowed", True),
    "network_pow_registration_allowed": (
        "sudo_set_network_pow_registration_allowed",
        False,
    ),
    "yuma3_enabled": ("sudo_set_yuma3_enabled", False),
    "alpha_sigmoid_steepness": ("sudo_set_alpha_sigmoid_steepness", True),
    "user_liquidity_enabled": ("toggle_user_liquidity", True),
    "bonds_reset_enabled": ("sudo_set_bonds_reset_enabled", False),
    "transfers_enabled": ("sudo_set_toggle_transfer", False),
    "min_allowed_uids": ("sudo_set_min_allowed_uids", True),
}

HYPERPARAMS_MODULE = {
    "user_liquidity_enabled": "Swap",
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
    "MECHANISMS": {
        "CONFIG": "Mechanism Configuration",
        "EMISSION": "Mechanism Emission",
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
    "LIQUIDITY": {
        "LIQUIDITY_MGMT": "Liquidity Management",
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
        HEADER = "#4196D6"  # Light Blue
        LINKS = "#8CB9E9"  # Sky Blue
        HINT = "#A2E5B8"  # Mint Green
        COLDKEY = "#9EF5E4"  # Aqua
        HOTKEY = "#ECC39D"  # Light Orange/Peach
        SUBHEADING_MAIN = "#7ECFEC"  # Light Cyan
        SUBHEADING = "#AFEFFF"  # Pale Blue
        SUBHEADING_EXTRA_1 = "#96A3C5"  # Grayish Blue
        SUBHEADING_EXTRA_2 = "#6D7BAF"  # Slate Blue
        CONFIRMATION_Y_N_Q = "#EE8DF8"  # Light Purple/Pink
        SYMBOL = "#E7CC51"  # Gold
        BALANCE = "#4F91C6"  # Medium Blue
        COST = "#53B5A0"  # Teal
        SUCCESS = "#53B5A0"  # Teal
        NETUID = "#CBA880"  # Tan
        NETUID_EXTRA = "#DDD5A9"  # Light Khaki
        TEMPO = "#67A3A5"  # Grayish Teal
        ARG = "dark_orange"
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
        TAO = "#4F91C6"  # Medium Blue
        SLIPPAGE_TEXT = "#C25E7C"  # Rose
        SLIPPAGE_PERCENT = "#E7B195"  # Light Coral
        NOT_REGISTERED = "#EB6A6C"  # Salmon Red
        EXTRA_1 = "#D781BB"  # Pink
        # aliases
        AMOUNT = STAKE_AMOUNT
        ALPHA = STAKE_ALPHA
        SWAP = STAKE_SWAP

    class Pools(Gettable):
        TAO = "#4F91C6"  # Medium Blue
        ALPHA_IN = "#D09FE9"  # Light Purple
        ALPHA_OUT = "#AB7CC8"  # Medium Purple
        RATE = "#F8D384"  # Light Orange
        TAO_EQUIV = "#8CB9E9"  # Sky Blue
        EMISSION = "#F8D384"  # Light Orange
        EXTRA_1 = "#CAA8FB"  # Lavender
        EXTRA_2 = "#806DAF"  # Dark Purple

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
        HYPERPARAMETER = "#4F91C6"  # Medium Blue
        VALUE = "#D09FE9"  # Light Purple
        NORMALIZED = "#AB7CC8"  # Medium Purple
        # aliases
        HYPERPARAM = HYPERPARAMETER
        NORMAL = NORMALIZED


COLOR_PALETTE = ColorPalette()
COLORS = COLOR_PALETTE
