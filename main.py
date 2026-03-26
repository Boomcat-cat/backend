from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
# 替换bcrypt：用Python内置的hashlib
import hashlib
import pandas as pd
from services.r_engine import run_inversion_model
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # 1. 引入 CORS 中间件
from pydantic import BaseModel
import os

from services.r_engine import run_inversion_model

app = FastAPI()

# 2. 配置跨域允许规则 (极其关键)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有域名访问 (包括 localhost:5173 和 Vercel)。安全性要求高时，可替换为具体的域名列表。
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法 (POST, GET, OPTIONS 等)
    allow_headers=["*"],  # 允许所有请求头
)

# 挂载静态目录
os.makedirs("static/results", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
# ========== 调用R进行反演 ==========
app = FastAPI()


# 定义前端传过来的数据结构格式
# ================= 新增：挂载静态目录 =================
# 确保项目目录下有一个 static/results 文件夹
os.makedirs("static/results", exist_ok=True)
# 这一行极其关键：它允许外部通过 /static/... 路径直接访问硬盘上的图片
app.mount("/static", StaticFiles(directory="static"), name="static")


# ====================================================

class PixelData(BaseModel):
    X: list[float]
    Y: list[float]
    R: list[float]
    G: list[float]
    B: list[float]


@app.post("/api/inversion/stitched")
async def process_stitched_image(
        file: UploadFile = File(...),
        overlap: int = Form(default=85)
):
    temp_image_path = f"temp_{file.filename}"

    try:
        # 1. 接收并保存前端传来的真实图片文件
        image_bytes = await file.read()
        with open(temp_image_path, "wb") as f:
            f.write(image_bytes)

        # 2. 使用 rasterio 读取图像并提取像素特征
        with rasterio.open(temp_image_path) as src:
            # 读取前三个波段 (通常是 R, G, B)
            # flatten() 将二维矩阵展平为一维数组
            band_r = src.read(1).flatten()

            # 兼容单波段灰度图或双波段图像的情况
            band_g = src.read(2).flatten() if src.count >= 2 else band_r
            band_b = src.read(3).flatten() if src.count >= 3 else band_r

            # 构建图像的像素坐标网格 (X 为列号，Y 为行号)
            cols, rows = np.meshgrid(np.arange(src.width), np.arange(src.height))
            x_coords = cols.flatten()
            y_coords = rows.flatten()

        # 3. 组装为 Pandas DataFrame
        df = pd.DataFrame({
            'X': x_coords,
            'Y': y_coords,
            'R': band_r,
            'G': band_g,
            'B': band_b
        })

        # 4. 内存优化：剔除无效背景像素 (NoData)
        # 无人机拼接影像边缘通常有大量纯黑 (0,0,0) 或纯白 (255,255,255) 的无效区域
        # 将这些像素过滤掉，可大幅减轻 R 语言模型的运算压力和内存占用
        valid_pixels_mask = ~((df['R'] == 0) & (df['G'] == 0) & (df['B'] == 0)) & \
                            ~((df['R'] == 255) & (df['G'] == 255) & (df['B'] == 255))

        clean_df = df[valid_pixels_mask].copy()

        # 5. 传递给 R 语言引擎进行反演计算
        # result 字典应包含 'dataframe' 和 'filename'
        result = run_inversion_model(clean_df)

        # 6. 拼接生成的图片 URL
        image_url = f"http://localhost:5173/static/results/{result['filename']}"

        return {
            "status": "success",
            "message": "反演计算完成",
            "image_url": image_url
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图像处理或反演计算失败: {str(e)}")

    finally:
        # 7. 无论成功还是失败，最后强制清理临时文件释放硬盘空间
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
# ========== 配置（零基础直接复制） ==========
# JWT密钥（随便写一个长字符串，用于加密登录状态）
SECRET_KEY = "your-secret-key-water-monitor-2026"
ALGORITHM = "HS256"
# 加盐值（固定字符串，增加加密安全性，随便写）
SALT = "water-monitor-salt-2026"

# ========== 关键修复：先定义oauth2_scheme，再用它 ==========
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ========== 数据库配置 ==========
engine = create_engine('sqlite:///water_monitor.db', connect_args={"check_same_thread": False})
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# ========== 数据库表定义 ==========
# 用户表
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True) # 用户名
    hashed_password = Column(String(200)) # 加密后的密码
    is_admin = Column(Boolean, default=False) # 是否是管理员

# 申请记录表
class ApplyRecord(Base):
    __tablename__ = "apply_records"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer) # 提交申请的用户ID
    area = Column(String(200))
    cloud_cover = Column(Integer)
    date_range = Column(String(100))
    products = Column(String(200))
    task_id = Column(String(50), unique=True)
    status = Column(String(20), default="待处理") # 待处理/处理中/已完成
    create_time = Column(DateTime, default=datetime.now)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# ========== 工具函数（核心：替换bcrypt的加密逻辑） ==========
# 获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 【替换】密码加密（用sha256+加盐）
def hash_password(password: str):
    # 密码 + 盐值 拼接后加密
    password_with_salt = (password + SALT).encode('utf-8')
    # 用sha256加密
    hashed = hashlib.sha256(password_with_salt).hexdigest()
    return hashed

# 【替换】密码验证
def verify_password(plain_password: str, hashed_password: str):
    # 明文密码加密后和数据库里的密文对比
    return hash_password(plain_password) == hashed_password

# 创建JWT token
def create_access_token(data: dict):
    to_encode = data.copy()
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# 验证JWT token，获取当前用户（现在oauth2_scheme已经定义了）
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="无法验证登录状态，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# ========== 数据模型 ==========
class UserCreate(BaseModel):
    username: str
    password: str

class SatelliteRequest(BaseModel):
    area: str
    cloud_cover: int
    date_range: str
    products: list[str]

class StatusUpdate(BaseModel):
    task_id: str
    status: str

# ========== 初始化：创建默认管理员账号（账号：admin，密码：admin123） ==========
def init_admin():
    db = SessionLocal()
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            hashed_password=hash_password("admin123"), # 用新的加密逻辑
            is_admin=True
        )
        db.add(admin)
        db.commit()
    db.close()

init_admin()

# ========== 接口：注册 ==========
@app.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    # 检查用户名是否已存在
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    # 创建新用户（用新的加密逻辑）
    hashed_pwd = hash_password(user.password)
    new_user = User(username=user.username, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "注册成功"}

# ========== 接口：登录 ==========
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 查找用户
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    # 创建token
    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "is_admin": user.is_admin
    }

# ========== 接口：提交卫星申请（需要登录） ==========
@app.post("/satellite/submit")
def submit_satellite_request(
    request: SatelliteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task_id = "TASK_" + str(int(time.time()))
    new_record = ApplyRecord(
        user_id=current_user.id,
        task_id=task_id,
        area=request.area,
        cloud_cover=request.cloud_cover,
        date_range=request.date_range,
        products=",".join(request.products),
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return {
        "task_id": task_id,
        "area": request.area,
        "message": "申请已提交"
    }


# ========== 接口：获取我的申请记录（需要登录） ==========
@app.get("/my-records")
def get_my_records(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    # 按时间倒序查询，最新的任务在最上面
    records = db.query(ApplyRecord).filter(ApplyRecord.user_id == current_user.id).order_by(
        ApplyRecord.create_time.desc()).all()

    # 【核心新增】：模拟 AI 引擎后台自动计算。超过 10 秒自动变为“已完成”
    changed = False
    for r in records:
        if r.status in ["待处理", "处理中"]:
            # 如果当前时间距离创建时间超过了 10 秒
            if (datetime.now() - r.create_time).total_seconds() > 10:
                r.status = "已完成"
                changed = True
            else:
                r.status = "处理中"  # 刚提交的变成处理中
                changed = True

    if changed:
        db.commit()  # 保存状态变更到数据库

    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "area": r.area,
            "cloud_cover": r.cloud_cover,
            "date_range": r.date_range,
            "products": r.products.split(","),
            "status": r.status,
            "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        for r in records
    ]

# ========== 接口：管理员获取所有申请记录（需要管理员权限） ==========
@app.get("/admin/records")
def get_all_records(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权访问")
    records = db.query(ApplyRecord).all()
    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "user_id": r.user_id,
            "area": r.area,
            "cloud_cover": r.cloud_cover,
            "date_range": r.date_range,
            "products": r.products.split(","),
            "status": r.status,
            "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        for r in records
    ]

# ========== 接口：管理员修改任务状态（需要管理员权限） ==========
@app.put("/admin/update-status")
def update_status(
    update: StatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="无权访问")
    record = db.query(ApplyRecord).filter(ApplyRecord.task_id == update.task_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    record.status = update.status
    db.commit()
    return {"message": "状态更新成功"}

# ========== 原有接口（无人机相关） ==========
# @app.get("/")
# def read_root():
#     return {"message": "欢迎使用水质监测智能平台！"}
#
# @app.post("/drone/upload")
# async def upload_drone_image(file: UploadFile = File(...)):
#     return {"filename": file.filename, "message": "文件上传成功"}
#
# @app.post("/drone/stitch")
# def stitch_image():
#     time.sleep(2)
#     return {"status": "success", "message": "PIE-SMART影像拼接完成！"}

@app.post("/drone/stitch")
def stitch_image():
    time.sleep(2)
    return {"status": "success", "message": "PIE-SMART影像拼接完成！"}

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="dist", html=True), name="static")