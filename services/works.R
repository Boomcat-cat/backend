rm(list = ls())

# 导入需要的包
library(randomForest)
library(caret)
library(class)
# ================= 新增画图依赖 =================
library(ggplot2)
library(viridis)
# ================================================

# 加载之前训练好的最佳模型
load_models <- function() {
  chla_model <- readRDS("chla_model.rds")
  turb_model <- readRDS("turbidity_model.rds")
  bga_model <- readRDS("bga_model.rds")
  
  return(list(
    chla_model = chla_model,
    turb_model = turb_model,
    bga_model = bga_model
  ))
}

# 预测函数 (新增了 output_dir 参数，指定图片存在哪里)
predict_levels <- function(our_data, output_dir = "./static/results") {
  # 加载模型
  models <- load_models()
  
  # 提取需要的特征
  features_rgb <- c("R", "G", "B")
  features_rgb_ha <- c("R", "G", "B", "HA")
  
  # 确定各模型使用的特征
  chla_features <- if(models$chla_model$features == "RGB+HA") features_rgb_ha else features_rgb
  turb_features <- if(models$turb_model$features == "RGB+HA") features_rgb_ha else features_rgb
  bga_features <- if(models$bga_model$features == "RGB+HA") features_rgb_ha else features_rgb
  
  # 初始化结果数据框
  result_df <- data.frame(
    X = our_data$X,
    Y = our_data$Y,
    Chla_level = NA,
    BGA_level = NA,
    Turbidity_level = NA
  )
  
  # 预测Chla_level
  chla_model_obj <- models$chla_model$model
  if (inherits(chla_model_obj, "randomForest")) {
    result_df$Chla_level <- predict(chla_model_obj, newdata = our_data[, chla_features])
  } else {
    stop("Chla模型类型未知")
  }
  
  # 预测Turbidity_level
  turb_model_obj <- models$turb_model$model
  if (inherits(turb_model_obj, "randomForest")) {
    result_df$Turbidity_level <- predict(turb_model_obj, newdata = our_data[, turb_features])
  } else {
    stop("Turbidity模型类型未知")
  }
  
  # 预测BGA_level
  bga_model_obj <- models$bga_model$model
  if (is.list(bga_model_obj) && "k" %in% names(bga_model_obj)) {
    bga_model_info <- bga_model_obj
    
    # 标准化特征
    new_scaled <- predict(bga_model_info$preproc, newdata = our_data[, bga_features])
    
    # 使用KNN预测
    result_df$BGA_level <- knn(
      train = predict(bga_model_info$preproc, bga_model_info$train_data)[, bga_features],
      test = new_scaled,
      cl = bga_model_info$train_data$BGA_level,
      k = bga_model_info$k
    )
  } else {
    stop("BGA模型类型未知")
  }
  
  # 将因子转换为数值
  result_df$Chla_level <- as.numeric(as.character(result_df$Chla_level))
  result_df$BGA_level <- as.numeric(as.character(result_df$BGA_level))
  result_df$Turbidity_level <- as.numeric(as.character(result_df$Turbidity_level))
  
  # ================= 新增：渲染空间分布热力图 =================
  # 1. 确保服务器上的输出目录存在
  if (!dir.exists(output_dir)) {
    dir.create(output_dir, recursive = TRUE)
  }
  
  # 2. 生成一个带时间戳的唯一图片名，防止并发时被覆盖
  img_filename <- paste0("chla_heatmap_", as.numeric(Sys.time()) * 1000, ".png")
  img_filepath <- file.path(output_dir, img_filename)
  
  # 3. 使用 ggplot2 极速渲染热力图
  # geom_raster 专为密集的像素矩阵优化，渲染速度极快
  # 为了不遮挡前端的深色 UI，这里我们把图表的背景设为透明 (fill = NA)
  p <- ggplot(result_df, aes(x = X, y = Y, fill = Chla_level)) +
    geom_raster() +
    scale_fill_viridis_c(option = "turbo", name = "Chla") + # turbo 是一种非常适合展示水华分布的高对比度色板
    coord_fixed() + # 锁定 XY 比例，防止无人机影像被拉伸畸变
    theme_void() +  # 拔掉所有坐标轴、网格线和灰色底板
    theme(
      plot.background = element_rect(fill = "transparent", color = NA),
      panel.background = element_rect(fill = "transparent", color = NA),
      legend.position = "none" # 隐藏图例，因为你的前端 UI 右下角已经自己画了一个完美的图例框了
    )
  
  # 4. 导出为高精度 PNG (dpi=300 保证在网页上放大看细节依然清晰)
  ggsave(filename = img_filepath, plot = p, width = 10, height = 8, dpi = 300, bg = "transparent")
  # ============================================================
  
  # 核心改变：以前只返回数据框，现在返回一个“列表(List)”
  # 里面打包了原始数据和刚生成的图片路径
  return(list(
    data = result_df,
    image_path = img_filepath,
    filename = img_filename
  ))
}