import pandas as pd
import rpy2.robjects as robjects
from rpy2.robjects import pandas2ri
from rpy2.robjects.conversion import localconverter

converter = pandas2ri.converter

try:
    robjects.r['source']('works.R')
    r_predict_func = robjects.globalenv['predict_levels']
    print("R语言反演引擎加载成功")
except Exception as e:
    print(f"R环境加载失败: {e}")


def run_inversion_model(pixel_df: pd.DataFrame) -> dict:
    """
    修改后：返回一个字典，包含 DataFrame 和 生成的图片文件名
    """
    with localconverter(robjects.default_converter + pandas2ri.converter):
        # 1. 调用 R 函数，此时它返回的是一个 R 的 ListVector
        r_result_list = r_predict_func(pixel_df)

        # 2. 按照我们在 works.R 里定义的 list 名字提取内容
        r_df = r_result_list.rx2('data')
        # R 的字符串返回的是单元素向量，加上 [0] 取出纯字符串
        filename = r_result_list.rx2('filename')[0]

        # 3. 把 R 的表格转回 Python 的 DataFrame
        python_result_df = robjects.conversion.rpy2py(r_df)

    # 将表格和文件名一起打包返回给 main.py
    return {
        "dataframe": python_result_df,
        "filename": filename
    }