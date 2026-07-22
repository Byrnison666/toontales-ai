import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { riseItem, staggerContainer } from '../animations'
import { useAuth } from '../auth'
import { MagicButton } from '../components/MagicButton'
import { PageTransition } from '../components/PageTransition'

const steps = [
  {
    icon: '✍️',
    number: '01',
    title: 'Расскажи историю',
    description: 'Опиши героев, приключение и настроение — как подсказывает воображение.',
    color: 'from-rose-400/25 to-orange-300/10',
  },
  {
    icon: '🪄',
    number: '02',
    title: 'Мы добавим магию',
    description: 'ToonTales придумает сцены, нарисует мир, оживит его и подарит героям голоса.',
    color: 'from-violet-400/25 to-fuchsia-300/10',
  },
  {
    icon: '🎬',
    number: '03',
    title: 'Смотри мультфильм',
    description: 'Через несколько волшебных мгновений твоя сказка готова к семейному просмотру.',
    color: 'from-cyan-400/25 to-emerald-300/10',
  },
] as const

export function LandingPage(): JSX.Element {
  const { isAuthenticated } = useAuth()
  const navigate = useNavigate()

  const startCreating = (): void => navigate(isAuthenticated ? '/create' : '/register')

  return (
    <PageTransition>
      <section className="relative isolate mx-auto flex min-h-[calc(100vh-4.5rem)] max-w-7xl items-center px-4 py-20 sm:px-6 lg:px-8 lg:py-24">
        <motion.div
          className="absolute left-[3%] top-[19%] hidden h-20 w-48 rounded-[50%] bg-white/8 blur-[1px] sm:block"
          animate={{ x: [0, 22, 0], y: [0, -8, 0] }}
          transition={{ duration: 8, repeat: Infinity, ease: 'easeInOut' }}
          aria-hidden="true"
        >
          <span className="absolute -left-6 bottom-0 h-14 w-20 rounded-full bg-white/8" />
          <span className="absolute left-14 -top-8 h-20 w-24 rounded-full bg-white/8" />
        </motion.div>
        <motion.div
          className="absolute right-[4%] top-[22%] hidden h-16 w-40 rounded-[50%] bg-cyan-100/6 blur-[1px] lg:block"
          animate={{ x: [0, -28, 0], y: [0, 12, 0] }}
          transition={{ duration: 10, repeat: Infinity, ease: 'easeInOut', delay: 1.4 }}
          aria-hidden="true"
        />

        <div className="relative z-10 mx-auto max-w-5xl text-center">
          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate="visible"
            className="flex flex-col items-center"
          >
            <motion.p
              variants={riseItem}
              className="mb-7 inline-flex items-center gap-2 rounded-full border border-amber-200/20 bg-amber-200/10 px-4 py-2 text-sm font-extrabold tracking-wide text-amber-100 shadow-[0_0_25px_rgba(251,191,36,0.12)]"
            >
              <motion.span
                animate={{ rotate: 360 }}
                transition={{ duration: 5, repeat: Infinity, ease: 'linear' }}
                aria-hidden="true"
              >
                ✦
              </motion.span>
              Твоя собственная анимационная студия
            </motion.p>
            <motion.h1
              variants={riseItem}
              className="font-display text-5xl font-bold leading-[0.98] tracking-tight text-white sm:text-7xl lg:text-[5.8rem]"
            >
              Преврати свою историю
              <span className="text-gradient mt-2 block pb-2">в мультфильм</span>
            </motion.h1>
            <motion.p
              variants={riseItem}
              className="mt-6 max-w-2xl text-lg leading-relaxed text-violet-200 sm:text-xl"
            >
              Напиши сюжет — а мы превратим слова в яркие сцены, живых героев и маленькое чудо, которым хочется делиться.
            </motion.p>
            <motion.div variants={riseItem} className="mt-10">
              <MagicButton
                onClick={startCreating}
                className="group min-h-16 rounded-[1.35rem] px-8 text-lg sm:px-10 sm:text-xl"
              >
                Создать свою сказку
                <motion.span
                  animate={{ rotate: [0, 16, -12, 0], scale: [1, 1.25, 0.95, 1] }}
                  transition={{ duration: 1.8, repeat: Infinity, repeatDelay: 0.8 }}
                  aria-hidden="true"
                >
                  ✨
                </motion.span>
              </MagicButton>
            </motion.div>
            <motion.div variants={riseItem} className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm font-bold text-violet-300">
              <span>✦ Оригинальный мир</span>
              <span>✦ Сцены с анимацией</span>
              <span>✦ Голоса и музыка</span>
            </motion.div>
          </motion.div>

          <motion.div
            className="relative mx-auto mt-16 h-40 max-w-3xl sm:h-52"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.65, type: 'spring', stiffness: 90, damping: 16 }}
            aria-hidden="true"
          >
            <div className="absolute inset-x-[12%] bottom-0 h-24 rounded-[50%] bg-violet-400/15 blur-2xl" />
            <motion.div
              className="absolute left-1/2 top-1/2 grid h-24 w-24 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-[2rem] border border-white/20 bg-gradient-to-br from-rose-300/80 via-violet-400/90 to-cyan-300/75 text-5xl shadow-[0_0_50px_rgba(196,181,253,0.5)] sm:h-32 sm:w-32 sm:text-6xl"
              animate={{ y: [-8, 8, -8], rotate: [-3, 3, -3] }}
              transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
            >
              🎞️
            </motion.div>
            {[0, 1, 2, 3, 4].map((spark) => (
              <motion.span
                key={spark}
                className="absolute text-amber-200"
                style={{ left: `${12 + spark * 19}%`, top: `${18 + (spark % 2) * 45}%` }}
                animate={{ y: [0, -14, 0], opacity: [0.3, 1, 0.3], scale: [0.8, 1.3, 0.8] }}
                transition={{ duration: 2.4 + spark * 0.35, repeat: Infinity, delay: spark * 0.25 }}
              >
                {spark % 2 === 0 ? '✦' : '✧'}
              </motion.span>
            ))}
          </motion.div>
        </div>
      </section>

      <section className="relative mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 lg:px-8 lg:pb-32" aria-labelledby="how-it-works">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-sm font-extrabold uppercase tracking-[0.25em] text-cyan-200">От идеи до премьеры</p>
          <h2 id="how-it-works" className="font-display mt-3 text-4xl font-bold text-white sm:text-5xl">
            Три шага до <span className="text-gradient">волшебства</span>
          </h2>
        </div>
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.2 }}
          className="mt-12 grid gap-5 md:grid-cols-3"
        >
          {steps.map((step) => (
            <motion.article
              key={step.number}
              variants={riseItem}
              whileHover={{ y: -9, rotate: step.number === '02' ? 0.7 : -0.7 }}
              className={`group relative overflow-hidden rounded-[2rem] border border-white/10 bg-gradient-to-br ${step.color} p-7 text-left shadow-[0_20px_70px_rgba(5,3,25,0.28)] backdrop-blur-xl`}
            >
              <span className="absolute right-5 top-4 font-display text-5xl font-bold text-white/[0.055]">{step.number}</span>
              <motion.div
                whileHover={{ scale: 1.15, rotate: 8 }}
                className="grid h-16 w-16 place-items-center rounded-2xl border border-white/15 bg-white/10 text-3xl shadow-inner"
              >
                {step.icon}
              </motion.div>
              <h3 className="font-display mt-6 text-2xl font-semibold text-white">{step.title}</h3>
              <p className="mt-3 leading-relaxed text-violet-200">{step.description}</p>
            </motion.article>
          ))}
        </motion.div>
      </section>
    </PageTransition>
  )
}
