package com.example.driverrewards.ui.catalog

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.View
import android.view.animation.LinearInterpolator

class ShimmerView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val gradientMatrix = Matrix()
    private var shimmerGradient: LinearGradient? = null
    private var animator: ValueAnimator? = null
    private var gradientWidth = 0f

    init {
        paint.shader = null
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (w > 0 && h > 0) {
            setupGradient(w, h)
            startShimmer()
        }
    }

    private fun setupGradient(width: Int, height: Int) {
        // Create a gradient that's wider than the view for smooth animation
        gradientWidth = width * 1.5f
        
        // Create a more liquid-like gradient with smoother transitions
        // The gradient is defined in local coordinates, then translated via matrix
        shimmerGradient = LinearGradient(
            0f, 0f, gradientWidth * 2f, 0f,
            intArrayOf(
                0x00BDBDBD.toInt(),  // Fully transparent dark gray
                0x40BDBDBD.toInt(),  // Semi-transparent dark gray
                0xFFE8E8E8.toInt(),  // Bright light gray (highlight)
                0xFFE0E0E0.toInt(),  // Light gray
                0xFFE8E8E8.toInt(),  // Bright light gray (highlight)
                0x40BDBDBD.toInt(),  // Semi-transparent dark gray
                0x00BDBDBD.toInt()   // Fully transparent dark gray
            ),
            floatArrayOf(0f, 0.2f, 0.4f, 0.5f, 0.6f, 0.8f, 1f),
            Shader.TileMode.CLAMP
        )
        
        paint.shader = shimmerGradient
    }

    private fun startShimmer() {
        stopShimmer()
        
        val viewWidth = width.toFloat()
        animator = ValueAnimator.ofFloat(-gradientWidth, viewWidth + gradientWidth).apply {
            duration = 1500  // Faster animation for more liquid feel
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            
            addUpdateListener { animation ->
                val translateX = animation.animatedValue as Float
                gradientMatrix.reset()
                gradientMatrix.setTranslate(translateX, 0f)
                shimmerGradient?.setLocalMatrix(gradientMatrix)
                invalidate()
            }
            
            start()
        }
    }

    private fun stopShimmer() {
        animator?.cancel()
        animator = null
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), paint)
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (width > 0 && height > 0) {
            startShimmer()
        }
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        stopShimmer()
    }
}

