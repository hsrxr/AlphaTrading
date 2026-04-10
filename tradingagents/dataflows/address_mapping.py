TOKENS = {
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  
    "WETH": "0x4200000000000000000000000000000000000006", 
    "cbBTC": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 
    "AERO": "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 
}


AERODROME_PAIRS = {

    "WETH/USDC": "0xB4885Bc63399BF5518b994c1d0C153334Ee579D0", 
    "ETHUSD": "0xB4885Bc63399BF5518b994c1d0C153334Ee579D0",
    "ETH/USDC": "0xB4885Bc63399BF5518b994c1d0C153334Ee579D0",

    "BTCUSD": "0x4e962BB3889Bf030368F56810A9c96B83CB3E778",
    "BTC/USDC": "0x4e962BB3889Bf030368F56810A9c96B83CB3E778",
    "cbBTC/USDC": "0x4e962BB3889Bf030368F56810A9c96B83CB3E778",

    "SOLUSD": "0xb30540172F1B37d1eE1d109e49F883E935E69219",
    "SOL/USDC": "0xb30540172F1B37d1eE1d109e49F883E935E69219",

    "WETH/cbBTC": "0x...", 
    

    "AERO/USDC": "0xcdCdf86b2dBf05Ee18e001bdDb5235555d49F7D0",
    "AERO/WETH": "0x...",
    

    "DEGEN/WETH": "0x...",
}



def get_token_address(symbol: str) -> str:
    """根据代币缩写获取其智能合约地址"""
    address = TOKENS.get(symbol.upper())
    if not address:
        raise ValueError(f"❌ 未在 config.py 中找到代币: {symbol}")
    return address

def get_pair_address(pair_symbol: str) -> str:
    """
    根据交易对名称（如 'WETH/USDC'）获取其 Aerodrome 池子地址
    """
    address = AERODROME_PAIRS.get(pair_symbol.upper())
    if not address or address == "0x...":
        raise ValueError(f"❌ 交易对 {pair_symbol} 的池地址未配置或无效，请更新 config.py")
    return address